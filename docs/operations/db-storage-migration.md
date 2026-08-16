# 搬遷資料庫到另一個 storage class

**適用**：任何叢集要改 `db_storage_class` 的時候。

`storageClassName` 是 immutable，所以這不是重新渲染，是 **dump 與 restore**。這份文件是
那個程序唯一寫下的地方——per-cluster 的 issue 只記錄該次執行的數字與結果，**不複述步驟**。

已知執行紀錄：jcom（2026-08-13，`local-path`）、jg-jiahd（進行中，`ferry133/jg-jiahd#1`，
`longhorn`）。

---

## 先決定目的地

| 叢集形狀 | 正確的 `db_storage_class` | 理由 |
|---|---|---|
| 單節點 | `local-path` | 在一個節點上「釘住」本來就成立 |
| 多節點、無複製式儲存 | `local-path` + **明寫 `accept_node_pinning: true`** | pod 會被釘死在單一節點，失去它就同時失去資料與重啟能力 |
| 多節點、有 Longhorn | **`longhorn`** | 唯一同時 block-backed 又不釘節點的 class |
| 任何 | `sc-nas` = **「還沒搬」的標記** | NFS 的 fsync 與鎖語意對資料庫本來就不對，永遠不是目的地 |

**沒有任何東西驗證你填的 class 會存在。** CUE 接受任何非空字串，`plugin.py` 只 `setdefault`，
沒有檢查腳本看它。填 `longhorn` 而叢集沒裝 Longhorn，`cue vet` 會過、`task configure` 會過、
渲染出的 PVC 會 **Pending 到天荒地老**，而且不像 LB-IPAM 那樣有 `IPAMRequestSatisfied=False`
可看——只有一個沒人注意的 Pending。

所以動手前**自己確認目的地存在**：

```sh
kubectl get sc <class>
# Longhorn 另外要逐節點確認前置條件，見 replicated-storage.md
kubectl get nodes.longhorn.io -n longhorn-system -o json | jq -r \
  '.items[] | .metadata.name as $n | .status.conditions[] | [$n,.type,.status] | @tsv'
```

---

## 程序

以 `extras/default/postgres`（Kustomization `extras-postgres`、PVC `db/postgres-data`）為例；
其他資料庫 extra 同型，換掉名稱即可。

### 1. 先 suspend——在改任何東西之前

```sh
# 先找出「誰擁有那個 PVC」，不要猜
kubectl get kustomization -A -o custom-columns='NAME:.metadata.name,PATH:.spec.path'
```

`extras/<ns>/<app>` 是**父**，它通常只管一個物件：子 Kustomization。PVC 與 Deployment
由路徑結尾是 **`/app`** 的那個**子**擁有，而它每小時自己 reconcile。

```sh
flux suspend kustomization postgres      # 子，路徑 .../postgres/app
```

> ⚠️ **suspend 父的沒有用，而且是最壞的失敗形狀**：子仍然照常 reconcile，D38 的競態窗口
> 完全敞開，**但畫面看起來是關上的**。實測確認 `flux reconcile kustomization extras-postgres`
> **不會**清掉子的 suspend，所以父可以維持運作，爆炸半徑是一個 Kustomization 不是兩個。

**在 push 之前 suspend**，不是之後。之後 suspend 仍會讓 Flux 嘗試一次 immutable 的套用；
先 suspend 則那一次也不會發生——`kubectl get ks -A` 應該全程 **0 個 not-ready**，
daily-check 的第 2 項不可能 FAIL，healthchecks.io 的 ping 也不會被扣住。

**這兩件事的取捨**：suspend 期間該 app 收不到任何其他變更。窗口該是幾小時，不是幾天。

### 2. 改設定並推出去

```yaml
# cluster.yaml
db_storage_class: "longhorn"
```

```sh
task configure && git add ... && git commit && git push
```

**這個值刻意領先資料**：叢集必須在舊 PVC 被刪之前就知道新的 class。

### 3. 基準 dump——**只用於估算與比對，不是要還原的那一份**

```sh
kubectl exec -n db deploy/postgres -- pg_dump -U <user> <db> > baseline.sql
```

記下 **byte 數與逐表列數**。先量清楚要搬的是什麼：

> **磁碟佔用不是資料量。** 一座叢集的 `postgres` 維護資料庫可能有幾 MB 卻 **0 張使用者
> 表**——`initdb` 會在新卷上重建它，不需要搬。實際 payload 往往小一到兩個數量級。
> jg-jiahd 的例子：磁碟看起來 16 MB，真正要搬的是 `linebot` 的 10 張表、314 列、205 KB。

### 4. ⛔ 停下來，取得授權

**刪除 PVC 是破壞性且不可逆的。** 拿著 dump 的實際大小去問人，不要從任務授權繼承。
agent 尤其不可以自行跨過這一步（見 `docs/deploy/combinations.md` §2）。

### 5. 停寫、重新 dump

**授權後的第一個動作，不是刪除。**

第 3 步那份 dump 在你等待授權的期間就開始過期了。有寫入者持續連著的話——
web app、bot、agent——**暫停期間寫進去的每一筆都會被靜默丟掉**，而還原後的比對會通過，
因為你比對的是舊基準。

```sh
kubectl scale deploy/<writer> -n <ns> --replicas=0    # 每一個會寫的
kubectl exec -n db deploy/postgres -- pg_dump -U <user> <db> > restore.sql
```

**要還原的是這一份。** 第 3 步那份只用來確認規模與事後比對差異。

### 6. 縮到 0，再刪 PVC

```sh
kubectl scale deploy/postgres -n db --replicas=0
kubectl delete pvc postgres-data -n db
```

**縮到 0 是必要的**：有 pod 掛著的 PVC 會卡在 `pvc-protection` finalizer 上停在
`Terminating`——看起來像指令當掉。而這件事**只有在 Kustomization 已 suspend 時才安全**，
否則 Flux 立刻把它拉回 1。

> **第三道安全網**：`sc-nas` 若設了 `archiveOnDelete: "true"`（nfs-subdir 的預設），NFS 上的
> 目錄是被**改名**成 `archived-pvc-<uid>` 而不是刪除。確認你的 provisioner 是否如此——
> 這不是替代 dump，但在最壞的情況下它是最後一份原始資料。

### 7. 確認叢集上的值，再 resume

```sh
kubectl get secret cluster-secrets -n flux-system \
  -o jsonpath='{.data.DB_STORAGE_CLASS}' | base64 -d; echo   # 必須是新的 class
flux resume kustomization postgres      # 子，與第 1 步 suspend 的同一個
```

**push 不等於叢集知道**——`cluster-secrets` 是獨立的 Kustomization，有自己的節奏。
suspend 已經讓這一步不再是唯一防線，但它仍然是確認新 PVC 會用對 class 的地方。

### 8. Restore

**先確認 role 存在，再還原。** `pg_dump` 的輸出不會建立 role；缺了它，dump 裡每一個
`OWNER TO` 都會失敗，**而表照樣會被建出來**——看起來成功，擁有者卻是別人。
（`deployment-profiles` 6.9 在 jg-jiahd 的還原演練中發現。）

但先查清楚**這座叢集實際有哪些 role**，不要照抄：

```sh
kubectl exec -n db deploy/postgres -- psql -U <user> -At -c \
  "SELECT rolname FROM pg_roles WHERE rolcanlogin;"
```

如果 dump 的 owner 就是 `POSTGRES_USER`，`initdb` 會在新卷上自動建立它，**這一步不需要
任何動作**。jg-jiahd 就是這種：唯一的可登入角色是 `linebot`，沒有 `postgres` role，
6.9 的失效模式在那裡不可能發生。會需要預先建立的是 dump 引用了 `POSTGRES_USER` 以外的
owner 的情況。

```sh
kubectl exec -n db deploy/postgres -- psql -U <admin> -c "CREATE ROLE <owner> LOGIN;"
kubectl exec -i -n db deploy/postgres -- psql -U <admin> <db> < dump.sql
```

### 9. 逐表比對

```sh
kubectl get pvc postgres-data -n db   # storageClassName 應為新的 class
# 逐表列數與第 3 步記下的數字比對
```

---

## 回退

第 6 步之前，回退是免費的：`flux resume kustomization <子>`、把 `db_storage_class` 改回原值、
`task configure`、push。叢集回到原狀，沒有任何資料被動過。

第 6 步之後就沒有回退，只有從 dump 重建——所以第 5 步那份 dump 是唯一的資料來源，第 3 步的數字則是比對它的依據。

---

## 每次執行後要回寫的東西

**這是這份文件存在的理由。** 執行發生在 user repo，但**經驗不屬於那個 repo**：

- 該次執行的數字與結果 → 該 user repo 的 issue
- **任何可推廣的發現 → 回到這份文件**，或 `deployment-profiles` 的 design.md

D38（順序競態）就是這樣從 jcom 那次長出來的。第 1 步的 suspend 改良、第 5 步的重新 dump，都來自 jg-jiahd 那次。
若第三座叢集發現新東西而只寫在自己的 issue 裡，下一個人就會重新踩一遍——
**而重踩的代價在這個程序裡是一個資料庫。**
