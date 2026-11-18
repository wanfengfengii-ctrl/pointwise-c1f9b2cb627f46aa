# 更正单交接说明

白班按单号分次录入标签更正，质控员试算当前版，夜班只领取试算过的确切版次所签发的成果。

## 不变量

同一 `(ticket, version)` 上，**试算资格、候选页证据与成功归属**始终指向同一批候选固定页：

1. **资格**：`correction_previews` 只由 `preview_correction` 成功返回时写入，键为
   `(ticket, version)`，按父目录原序存 `page_no` 与候选页正文的 SHA-256。任何一批新的
   `record_edits` 成功都会提升 `correction_tickets.version` 并删除该单的全部试算行，因此
   已试算资格只可能属于当前版次；失败的录入批次连同其校验异常一起回滚，不改变版次、
   编辑和资格。超容量试算抛 `PageCapacityError` 并在事务内回滚，不留下资格。
2. **证据**：试算摘要由父成果的固定页加上当前版全部编辑按 V1 整单规则重算得到，
   覆盖父目录的每一页（未改页沿用父页正文），页序即父目录顺序，`digest` 为该页正文字节
   的 SHA-256 小写十六进制。试算不写入任何成果、回执或源码绑定。
3. **归属**：`sign_correction` 在同一写事务内依次检查单号存在、尚未签发、版次等于当前版、
   该版存在试算，并重新计算候选页后逐页比对摘要。只有全部匹配才写入固定页目录、原回执、
   `correction_signatures(ticket, version, release_id)` 并把单据置为关闭；任一检查失败都不
   写入。因此签发成果的页号、原序和摘要必然等于该版试算证据，且 `release_id` 与
   `(ticket, version)` 一一绑定（`release_id` 唯一约束）。

由此推出：签发后不会再有新录入（关闭标记），同单同版重投命中 `correction_signatures`
直接返回原成果号且不执行 `before_commit`，其他版次不能领取该成果；而列出该单所有
已试算版次，即可在重开数据库后复核夜班唯一可领取的那一版。

## 事务与重试

`record_edits`、`preview_correction`、`sign_correction` 各自使用 `BEGIN IMMEDIATE` 连接，
单据、版次、编辑、试算和签名绑定都持久化在 SQLite 中，`initialize_store` 重复执行只补建
表，已有成果、单据与资格原样保留。`sign_correction(before_commit=...)` 钩子在固定页、回执、
签名绑定和关闭标记写入后、提交前运行；钩子异常原样传播并回滚整个事务，其他连接看不到
本次成果或绑定，单据仍为开启且该版资格仍在，可原版次重试。

## 运行与演示

```sh
python3 -B -S handoff.py verify   # 全部原回归 + 更正单联合核验（v1 与 workflow 样例）
python3 -B -S handoff.py demo     # 晚到录入、签发回滚重试、重开后的复核结果
```

`demo` 在一份满页父成果上依次：版 1 录入后试算 257 槽失败；版 2 试算成功但被版 3 的晚到
录入作废并拒绝签发；版 3 签发前用钩子中断，重开后原版次重试成功，重投返回同一成果号，
录入已关闭；最后按原 `review.open_artifact` 与 `reconciliation.statement` 入口复核页序
`(10, 4)`、扩展原字节与 `N` 的净额 3。
