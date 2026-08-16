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

### 1. 改設定並推出去

```yaml
# cluster.yaml
db_storage_class: "longhorn"
```

```sh
task configure && git add ... && git commit && git push
```

**這個值刻意領先資料**：叢集必須在舊 PVC 被刪之前就知道新的 class。

### 2. 立刻 suspend 該 Kustomization

```sh
flux suspend kustomization extras-postgres
```

**這一步做兩件事，兩件都重要：**

- **消除 D38 的競態。** 舊做法是「確認叢集拿到新值後再刪 PVC」，因為 Flux 會在那個時間窗裡
  用舊值重建 PVC——jcom 就是這樣，而 immutable 的欄位讓它必須被刪第二次。**suspend 期間
  Flux 根本不能重建 PVC，那個窗口不存在了。**
- **避免一次假警報。** 不 suspend 的話，Flux 會持續嘗試把新的 `storageClassName` 套到現有
  PVC 上，那個欄位 immutable，於是該 Kustomization 整段時間都是 reconcile 錯誤。
  daily-check 的第 2 項是「Flux Kustomizations all Ready」，所以**只要這段跨過 08:00，就會
  寄出一封 FAIL——而 FAIL 會扣住 healthchecks.io 的 ping**，變成一個健康叢集的雙路告警。

代價：suspend 期間該 extra 收不到任何其他變更。**這個窗口該是幾小時，不是幾天。**

### 3. Dump，並記下比對基準

```sh
kubectl exec -n db deploy/postgres -- pg_dump -U <user> <db> > dump.sql
```

記下 **byte 數與逐表列數**。還原後要逐項比對的就是這兩個數字——
「看起來有資料」不是驗證。

### 4. ⛔ 停下來，取得授權

**刪除 PVC 是破壞性且不可逆的。** 拿著 dump 的實際大小去問人，不要從任務授權繼承。
agent 尤其不可以自行跨過這一步（見 `docs/deploy/combinations.md` §2）。

### 5. 刪除 PVC

```sh
kubectl delete pvc postgres-data -n db
```

### 6. 確認叢集上的值，再 resume

```sh
kubectl get secret cluster-secrets -n flux-system \
  -o jsonpath='{.data.DB_STORAGE_CLASS}' | base64 -d; echo   # 必須是新的 class
flux resume kustomization extras-postgres
```

**push 不等於叢集知道**——`cluster-secrets` 是獨立的 Kustomization，有自己的節奏。
suspend 已經讓這一步不再是唯一防線，但它仍然是確認新 PVC 會用對 class 的地方。

### 7. Restore

**先建 role，再還原。** `pg_dump` 的輸出不會建立 role；缺了它，dump 裡每一個 `OWNER TO`
都會失敗，**而表照樣會被建出來**——看起來成功，擁有者卻全變成 `postgres`。
（`deployment-profiles` 6.9 在 jg-jiahd 上發現。）

```sh
kubectl exec -n db deploy/postgres -- psql -U <admin> -c "CREATE ROLE <owner> LOGIN;"
kubectl exec -i -n db deploy/postgres -- psql -U <admin> <db> < dump.sql
```

### 8. 逐表比對

```sh
kubectl get pvc postgres-data -n db   # storageClassName 應為新的 class
# 逐表列數與第 3 步記下的數字比對
```

---

## 回退

第 4 步之前，回退是免費的：`flux resume`、把 `db_storage_class` 改回原值、
`task configure`、push。叢集回到原狀，沒有任何資料被動過。

第 5 步之後就沒有回退，只有從 dump 重建——所以第 3 步的數字要在刪除前就記下來。

---

## 每次執行後要回寫的東西

**這是這份文件存在的理由。** 執行發生在 user repo，但**經驗不屬於那個 repo**：

- 該次執行的數字與結果 → 該 user repo 的 issue
- **任何可推廣的發現 → 回到這份文件**，或 `deployment-profiles` 的 design.md

D38（順序競態）就是這樣從 jcom 那次長出來的。第 2 步的 suspend 改良來自 jg-jiahd 那次。
若第三座叢集發現新東西而只寫在自己的 issue 裡，下一個人就會重新踩一遍——
**而重踩的代價在這個程序裡是一個資料庫。**
