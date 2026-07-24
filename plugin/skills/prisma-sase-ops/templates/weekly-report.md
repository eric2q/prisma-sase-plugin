# Prisma SASE 租戶健康週報 — {{tenant_name}} ({{tsg_id}})

**期間**：{{start_date}} – {{end_date}}　**Region**：{{region}}　**產出**：{{generated_at}}

> 產製方式：依本模板呼叫 `prisma-sase` 工具收集 7 天資料。異常門檻（見
> `references/thresholds.md`）觸發時，請在下方 **重點摘要** 置頂並標紅。

---

## 0. 重點摘要 (Executive Summary)

<!-- 3–5 句。先講紅旗，再講整體。範例門檻：P1>0、ADEM 週跌>10、tunnel down。 -->

- 🔴 / 🟢 **整體狀態**：{{headline_from_get_sase_status}}
- **需要注意**：{{top_1_2_actionable_items_or_"無"}}

## 1. 告警 (Alerts)

*來源：`query_alerts(hours=168)`*

| Severity (P-level) | 數量 | 週變化 |
|---|---|---|
| Critical (P1) | {{n}} | {{delta}} |
| High (P2) | {{n}} | {{delta}} |
| Medium (P3) | {{n}} | {{delta}} |
| Low / info | {{n}} | {{delta}} |

**值得注意的告警**（新到舊，含時間）：
- {{severity}} · {{raised_time}} · {{category}} — {{message}}

## 2. 使用者體驗 (ADEM)

*來源：`get_user_experience(hours=168)`（整體）+ 重點使用者/應用*

- **整體分數**：{{score}} — {{rating}}（週變化 {{delta}}；門檻：跌 >10 標紅）
- **分數組成**：LAN {{lan}} / WiFi {{wifi}} / DNS {{dns}} / App {{app}}
- **最弱環節**：{{worst_component}} → {{interpretation}}
- **體驗較差的使用者/應用**：{{list_or_"無"}}

## 3. 連線與容量 (Connectivity & Capacity)

*來源：`get_sase_status()` 的 connectivity 段 + `get_connected_users(hours=168)`*

- **Tunnel 狀態**：up {{up}} / down {{down}}。Down：{{down_names_with_type_or_"無"}}
- **連線使用者**：尖峰 {{peak}} / 平均 {{avg}}；主要 location：{{top_locations}}
- **容量觀察**：{{capacity_note}}

## 4. 建議 (Recommendations)

<!-- 依上面資料給 1–3 條可執行建議；沒有問題就寫「本週無需處理事項」。 -->

1. {{recommendation}}

---

*本報告由唯讀工具產生，僅供監測；不含任何組態變更。資料可能含使用者名稱等資訊，
對外分享前請確認資料處理政策（design doc sec.7）。*
