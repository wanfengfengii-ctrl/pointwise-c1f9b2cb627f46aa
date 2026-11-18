# 仪器交换包交班库

精密仪器检测中心的台架操作员每天交付数据包。白班资料员接纳原件，按台架页号和物理行位更正普通观测的标签。夜班质控员脱离台架后，凭固定成果号复核原页、设备扩展和更正前后的账目。

## 运行

在项目根目录使用 Python 3.11。运行入口只使用标准库。演示和测试各自创建隔离临时库。

```sh
python3 -B -S handoff.py verify
python3 -B -S handoff.py demo
python3 -B -S -m unittest discover -s tests -p 'test_*.py' -v
```

演示接纳 `samples/shift.json`，发布物理行 `(10, 0)` 的更正，再用新连接读取两页和两份成果的账目。页 10 原有两条 A，读数分别为 +6 和 −6，另有一条缺测 M。页 4 有一条 W，读数是 +5。更正将 +6 从 A 转到 N，扩展 `00ff` 仍在页 10 的位置 1 引用槽 0 的 A。演示随后在满页父成果上跑一遍更正单流程：晚到录入、签发回滚重试、重开后的逐页复核与账目；交接不变量见 `HANDOFF.md`。`verify` 运行全部原回归并串行执行 `ticket_examples.py v1` 与 `workflow`。

## 入口

数据库参数是 SQLite 文件路径。先调用 `publication.store.initialize_store(database)`。重复初始化保留已接纳的源包、固定内容、父链和回执。应用应通过业务接口管理内容。

| 入口 | 返回及业务保证 |
| --- | --- |
| `intake.package.accept_package(database, batch_no, raw)` | 原件成果号。同批号同原字节重投返回原号。 |
| `correction.request.correct_labels(database, parent_id, edits)` | 子成果号。`edits` 是非空的 `correction.targets.LabelEdit(page_number, row_index, label)` 可迭代序列。每次成功更正创建独立子成果。 |
| `correction.request.record_edits(database, ticket, parent_id, edits)` | 版次号。首次成功录入固定父成果并返回 `1`，此后每批版次加一。同坐标覆盖，其余坐标保留；整批合法时超容量也保存。 |
| `correction.request.preview_correction(database, ticket, version)` | `(version, ((page_number, digest), ...))`。按 V1 规则整单试算当前未签发版，摘要按父目录页序含未改页；成功即建立该版签发资格。 |
| `publication.commit.sign_correction(database, ticket, version, *, before_commit=None)` | 成果号。只签发当前已试算版，逐页核对摘要后把固定页、原回执和单号版次绑定一并提交，并关闭录入。 |
| `publication.receipts.read_receipt(database, release_id)` | `Receipt(release_id, batch_no, parent_id)`。原件的父号为 `None`。 |
| `review.open_artifact.read_page(database, release_id, page_number)` | `PageEvidence` 含成果号、页号和按原序排列的 `rows`，提供 `observations` 和 `extensions` 两个有序视图。 |
| `reconciliation.statement.reconcile_release(database, release_id)` | 标签有序的 `LabelTotal(label, records, non_null, net)` 元组。 |
| `reconciliation.statement.compare_releases(database, first, second)` | 标签有序的 `LabelDelta(label, records_delta, non_null_delta, net_delta)` 元组。 |

普通行证据含 `page_number`、`row_index`、`label` 与 `reading`。扩展证据含 `page_number`、`row_index`、`raw` 和 `references`。`references` 是原声明顺序的 `(slot, label)` 元组，重复引用也保留。所有行位从零开始，扩展占用物理行位。

接纳错误为 `intake.package.PackageError` 或 `publication.source_identity.SourceConflict`。更正坐标或新标签不合约时抛出 `correction.targets.CorrectionTargetError`，容量不足抛出 `correction.dictionary.PageCapacityError`，后者带页号和所需槽数。未知成果及目录外页分别抛出 `publication.catalog.ReleaseNotFound` 和 `PageNotFound`。缺失、损坏或不能解释的固定页抛出 `publication.page_format.FixedPageError`。已发布成果若缺少一致回执，抛出 `publication.receipts.ReceiptError`。平行分支和不同源批号成果不能比较，抛出 `publication.lineage.LineageError`。

接纳和更正支持可选的 `before_commit(pending_release_id)`。它在目录、固定页、回执及适用的源码字节绑定写入后、提交前运行。异常向调用方传播并回滚本次事务。原样重投直接返回既有成果号。公开接口只追加固定成果，保留父成果和未更正页的固定字节。

## 更正单流程

白班按单号分次录入，质控员按当前版整单试算，夜班凭试算过的版次签发。每批目标须在固定父成果上合法且唯一；有效批次使版次加一并使旧试算失效，整批超容量仍持久保存，失败批次保持原单据、版次和资格。试算只按原规则全量重算候选页并记录页号与 SHA-256 摘要，不写成果或回执；超容量时抛出 `PageCapacityError` 且不赋予资格。签发只接受当前版且该版已有试算；候选页须逐页匹配试算摘要，固定页、回执、`correction_signatures` 绑定和关闭标记同一事务提交。以已签发版次重投直接返回原成果号且不调用钩子，其他版次均拒绝。试算或签发未知单号抛 `KeyError`，其余无效单号、版次、换父成果、关闭后录入或过期试算、签发抛 `ValueError`。

## 源包与固定页

源批号是非空 UTF-8 文本。源包为 UTF-8 JSON 字节，外层有整数 `version`（值为 1）和有序 `pages` 数组，至少一页。每页有 `number`、`dictionary`、`rows`。页号在 1 至 4294967295 之间，包内唯一。字典为 `[slot, label]` 对的数组，槽号为 0 至 255 的唯一整数。标签是非空 UTF-8 文本，可以在多个槽重复。空页、稀疏字典和只有扩展使用的字典项均可保存。文本保留原值。

普通行为 `{"kind":"observation","slot":0,"reading":6}`，读数为台架最小计数单位的有符号整数或 `null`。扩展行为 `{"kind":"extension","hex":"00ff","refs":[0]}`，`hex` 为连续成对的十六进制字符，`refs` 为有序槽号数组。扩展正文只按字节存取。普通槽号和扩展引用必须已在当前页声明。布尔值和浮点值不能用作整数。JSON 对象重复键、额外字段、非法行种类和悬空引用均导致原包拒绝。

固定页正文以 `IPG1` 开头，随后为四字节页号、两字节槽数、字典和四字节行数。字典项为单字节槽和带四字节长度的 UTF-8 标签。行标记 0 为单字节槽加缺测，1 为单字节槽加带长度的有符号整数，2 为带长度的原扩展字节和带长度的单字节引用序列。长度和整数采用大端序，读数采用有符号二补码。固定正文与有序目录、SHA-256 校验及成功回执一起提交。每次复核只用指定成果中该页的字典。

所有更正坐标在同一份固定父成果上绑定。整批最终状态先固定扩展声明的每个物理槽及其值，再为尚未被这些槽值覆盖的不同普通标签计槽。每页最多 256 槽。申请中任一非法目标或不可表示页使整批拒绝。成功更正保留页号、行位、原序、读数、缺测及扩展原字节和固定引用。普通行码允许随字典重新分配。

## 核账

每个物理普通行计入其标签的记录数。整数行增加非空个数并以整数精度相加。没有任何非空读数时净额为 `None`，真实读数抵消时净额为整数零。标签按 Unicode 码点排列。比较接受同一父链的祖先与后代或同一成果自身，按实际旧到新方向对两侧标签并集给出差额。两侧都没有读数时净额差为空，其余情况以零计入无读数的一侧。有坏页时整个核账或比较请求失败。

完整回归覆盖合法与非法接纳、源重投、重复初始化、满页更正、扩展固定槽和同值槽、事务回滚、断源读回、固定页损坏、缺测账目、大整数和父链比较。
