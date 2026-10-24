# 家庭水电气账单技能（utility-bill-recorder）

> 本文件为开源发布版（脱敏模板）。部署时请将 `{{PLACEHOLDER}}` 替换为你的实际配置；
> 本地私有信息（账单数据、截图、腾讯文档 ID、邮箱、地址、域名）一律不进入版本库。

## 固定路径（部署时替换）

- 项目根目录：`{{PROJECT_ROOT}}`
- 数据库：`{{PROJECT_ROOT}}/data/utility.db`
- 站点目录：`{{PROJECT_ROOT}}/site`（nginx 服务端口见 INSTALL.md，公网域名 `{{PUBLIC_DOMAIN}}`）
- 站点数据文件：`{{PROJECT_ROOT}}/site/data.js`
- 截图目录：`{{PROJECT_ROOT}}/images/YYYY-MM/`（`site/images` 软链指向 `{{PROJECT_ROOT}}/images`）
- 数据脚本：`{{PROJECT_ROOT}}/scripts/utility.py`
- 站点同步脚本：`{{PROJECT_ROOT}}/scripts/sync_site.py`
- 腾讯文档在线表格：file_id=`{{TENCENT_DOC_FILE_ID}}`，链接 `{{TENCENT_DOC_URL}}`，子表 `{{TENCENT_DOC_SUB_SHEET}}`
- 腾讯文档文件夹：电费 `{{TENCENT_DOC_FOLDER_ELEC}}`，水费 `{{TENCENT_DOC_FOLDER_WATER}}`，燃气 `{{TENCENT_DOC_FOLDER_GAS}}`

每次写入必须使用上述绝对路径，禁止因会话/工作目录变化而改写到别处。

## 数据模型：按费种拆表（三张独立表）

- **多家庭独立**：`families` 表存家庭名；每条账单记录挂在某个家庭下，互不干扰。
- **按费种拆表（禁止回退单表宽表）**：账单不再存单张宽表，而是按费种拆为三张独立表，各自只保留本费种需要的字段，消除无关 NULL 冗余列：
  - `bills_water`（水费）：`id, family_id, bill_month, usage, usage_unit, prev_reading, cur_reading, water_unit_price(水费单价), sewage_unit_price(污水单价), water_fee(水费金额), sewage_fee(污水费金额), amount(水费总价), bill_date, image, note, current_tier, tier_remaining, year_usage, tier_detail, created_at`
  - `bills_electric`（电费）：`id, family_id, bill_month, usage, usage_unit, prev_reading, cur_reading, unit_price(综合/平均单价), peak_prev_reading, peak_cur_reading, valley_prev_reading, valley_cur_reading, peak_usage, peak_price, valley_usage, valley_price, amount(电费总价), bill_date, image, note, current_tier, tier_remaining, year_usage, tier_detail, created_at`
  - `bills_gas`（燃气费）：`id, family_id, bill_month, usage, usage_unit, prev_reading, cur_reading, unit_price, amount(燃气费总价), bill_date, image, note, current_tier, tier_remaining, year_usage, tier_detail, created_at`
- **总价概念（与电费峰谷一致）**：水费总价 `amount` = `water_fee`（水费金额）+ `sewage_fee`（污水处理费金额），对应电费总价 `amount` = 峰电费 + 谷电费（峰+谷合计）。**年度趋势图每个费种只画一个"总价"柱**（水费柱=amount、电费柱=amount、燃气柱=amount）；总价的分项明细（水费金额/污水费金额、峰/谷）在**月度明细表**和**用能明细堆叠柱**中分列展示。
- 腾讯文档表格表头（第 0 行，共 27 列）：
  `0家庭 | 1月份 | 2类型 | 3上次读数 | 4本次读数 | 5用量 | 6单位 | 7综合单价(元) | 8峰上期 | 9峰本期 | 10谷上期 | 11谷本期 | 12峰电量(kWh) | 13峰单价(元) | 14谷电量(kWh) | 15谷单价(元) | 16污水单价(元/m³) | 17当前档位 | 18本档剩余量 | 19年累计 | 20档位明细 | 21费用(元) | 22账单日期 | 23截图 | 24备注 | 25水费金额(元) | 26污水费金额(元)`
- **电费峰谷读数必须按账单原样分开（禁止合并）**：账单上"上期示数/本期示数"分别有峰、谷两行时，必须分别存入峰上期(8)、峰本期(9)、谷上期(10)、谷本期(11)四列，**不得**将峰谷读数相加成单个上期/本期读数，也不得只留一个合并示数。
- **分档计费必须记录**：水/电/燃气均按阶梯计费，每档单价不同都要记录。字段：
  - `current_tier`：当前处于第几档（如"第一档"）
  - `tier_remaining`：本档剩余量（年累计上限-年累计已用量）
  - `year_usage`：年累计用量
  - `tier_detail`：JSON 档位明细（每档上限/单价，电费含峰谷价，水费含分项**水费价+污水价+污水计费比例(0.9)+综合价**，燃气含单价）
  - **对应 CLI 参数**（0.3.2 起已开放，必须实际传入，否则网页阶梯进度条与档位卡无数据）：
    `--current-tier "第一档" --tier-remaining 207.5 --year-usage 12.5 --tier-detail '{"一档":{"上限":220,"综合价":4.05}}'`
- 类型枚举：water=水费 / electric=电费 / gas=燃气费。单位：水/气 `m³`，电 `kWh`。
- **同家庭同月份同类型唯一**：重复录入同一条按 upsert 覆盖，不产生重复行。
- **按 id 修改/删除必须指定费种**（0.3.2）：三张 bills 表各自独立自增，id 空间互不重叠，
  同一 id 可能同时存在于多张表。此时 `update` / `delete` 必须带 `--type water|electric|gas` 消歧，
  否则命令会报错拒绝执行（不会误伤其他费种的账单）。

## 网页展示规则（禁止混排）

- **月度明细表分项独立展示**：按月分别渲染水费表（含"水费金额 + 污水费金额"两列）、电费表（峰谷分项四列）、燃气表（单价/用量/费用）三张独立表，禁止跨类型合并混排。
- **年度趋势图按总价单柱**：水费柱数据源用 `amount`（=水费金额+污水费金额），电费柱数据源用 `amount`（=峰+谷合计），燃气柱用 `amount`；不得把水费拆成"水费/污水费"两个柱。tooltip 只显示各费种总价金额。
- **用能明细视图**：网页"年度趋势"与"数据汇总"之间新增"用能明细"区块：
  - 顶部费种切换 Tabs（水费/电费/燃气费）+ 年份选择；
  - 月度费用柱状图按分项**堆叠**展示：水费柱=水费金额段+污水费金额段、电费柱=峰电费段（peak_usage×peak_price）+谷电费段（valley_usage×valley_price）、燃气柱=单段 amount，柱顶标注总价金额，同图叠加用量折线（第二 Y 轴）；
  - 底部三段阶梯收费进度条（绿一档/黄二档/粉三档，第三档取 25% 宽度示意）：分界刻度显示阈值（水 220/300、电 3120/4800、气 310/520），指针定位当年累计用量（取所选年份该费种月份最大一条账单的 year_usage），信息卡显示当前档位、年累计用量、本档上限、本档剩余（第三档显示"已进入第三档"）、各档单价（水含综合单价与污水计费比例 0.9 说明，电含峰谷单价）。
- 每类账单的当前档位、本档剩余量都要在网页展示。

## 一、水费获取与处理方式

1. **获取**：用户发来水费账单截图（微信/支付宝缴费单、水务短信截图等）→ 保存原图到 `{{PROJECT_ROOT}}/images/<YYYY-MM>/`。
2. **解析**：用视觉/OCR 读取：账期月份、上期/本期读数、本期用量（m³）、应缴金额、账单日期。上海居民阶梯水价（推算用）：年用量 ≤220m³ 第一档（水费2.25+污水2.00×0.9=4.05元/m³）；220~300m³ 第二档（水费4.00+污水2.00×0.9=5.80元/m³）；>300m³ 第三档（水费6.99+污水2.00×0.9=8.79元/m³）。**污水费按用水量90%计收**（污水费=用量×90%×2.00），综合单价=水费单价+污水单价×0.9。账单未印阶梯时按年累计用量推算当前档位，备注注明"账单未印阶梯，按上海居民阶梯水价推算"。
3. **入库**：`utility.py add --type water` 写入 `bills_water` 表：prev_reading/cur_reading/usage/amount/water_unit_price(`--water-unit-price`)/sewage_unit_price(`--sewage-unit-price`；兼容旧参数 `--sewage-price`)/current_tier/tier_remaining/year_usage/tier_detail，并**必须**同时写入分项金额 `water_fee`（水费金额=用量×水费单价）与 `sewage_fee`（污水费金额=用量×污水计费比例×污水单价）。三端（数据库/网页/腾讯文档表格）各自独立记录这两个分项；`amount`=water_fee+sewage_fee。
4. **同步**：`sync_site.py` → 腾讯文档表格覆盖式写入（含第 25 列水费金额、第 26 列污水费金额）。

## 二、电费获取与处理方式

1. **获取**：
   - 用户发来电费截图 → 保存到 `{{PROJECT_ROOT}}/images/<YYYY-MM>/`；
   - 批量自动读取 → `manage.folder_list(folder_id="{{TENCENT_DOC_FOLDER_ELEC}}")` 列出腾讯文档电费文件夹，待处理标题形如原始上传名，已处理标题形如 `YYYYMM 账单.pdf`（跳过）。
2. **解析 PDF/截图**：
   - 账单月份取**账期月份**；
   - **峰谷示数**：上期示数（峰）、本期示数（峰）、上期示数（谷）、本期示数（谷）**四值分别读取**，对应 peak_prev_reading/peak_cur_reading/valley_prev_reading/valley_cur_reading；
   - 峰电量=峰本期-峰上期，谷电量=谷本期-谷上期，分别存入 peak_usage/valley_usage；
   - 单价兼容两种文本格式（名称在前 `居民分时,电压220V(平)电度电费 11 0.6170 6.79`，数字在前 `193 0.6170 119.08\n电_居民生活_居民分时(平)电度电费`），双正则兜底；
   - 费用取"本月应付电费"（amount=峰电费+谷电费合计）；"抵扣往月预存电费/本月实付电费"写入备注。
3. **上海居民阶梯电价（推算用）**：年用量 ≤3120kWh 第一档（峰0.617/谷0.307）；3120~4800kWh 第二档（峰0.677/谷0.337）；>4800kWh 第三档（峰0.977/谷0.487）。按年累计用量判断当前档位与本档剩余。
4. **入库+同步**：`utility.py add --type electric` 写入 `bills_electric` 表（峰谷四列、peak_usage/peak_price/valley_usage/valley_price、unit_price、amount）；表格写入时峰谷上期/本期四列必须分开填。

## 三、燃气费获取与处理方式

1. **获取（邮箱）**：用户提供邮箱（如 `{{EMAIL}}`），燃气账单由燃气公司平台发送到邮箱。用 browser agent 登录邮箱收件箱，搜索燃气账单邮件（主题含"燃气"/"账单"），提取 PDF 链接。
2. **下载**：将每封邮件的 PDF 链接 curl 下载到 `{{PROJECT_ROOT}}/temp_gas/gas_YYYY-MM.pdf`（200 校验），PDF 文本解析字段：户名、地址、户号、上期/本期读数、本期用量、单价、金额、结算周期、**年累计用量与阶梯剩余**（文本如"310-已达=剩余"）。
3. **上传腾讯文档燃气文件夹（用户强调）**：将 PDF 上传到燃气文件夹 `{{TENCENT_DOC_FOLDER_GAS}}`，命名格式**必须含地址**：`YYYYMM 账单-<地址>`。
4. **入库+同步**：`utility.py add --type gas` 写入 `bills_gas` 表（prev_reading/cur_reading/usage/unit_price/amount）。燃气档位：年 ≤310m³ 第一档（3.00元/m³）；310~520m³ 第二档（3.30元/m³）；>520m³ 第三档（4.20元/m³）。账单文本含"第一阶梯"字样时直接采用，剩余量=310-年累计。
5. **标记防重复**：已上传且已录入的 PDF 以"YYYYMM 账单-地址.pdf"标题为已处理标记，下次自动跳过。

## 通用录入流程（用户发来账单截图时）

1. 解析截图字段（缺项不编造，备注注明缺失项）。
2. 确认家庭：明示→用明示；未明示多家庭→ask_user 单选；单家庭→直接用；无家庭→自动创建。
3. 保存截图（必须）：压缩到 ≤1280px、JPEG ≤80、≤300KB；HEIC 先转 JPEG。
4. `utility.py add --type <water|electric|gas>` 写入本地库对应费种表（含峰谷/档位/分项字段）。
5. `sync_site.py` 同步网站并验证三处（本地 data.js → 本地服务 → 公网域名 data.js?v=版本号）。
6. 腾讯文档表格覆盖式更新（键=家庭+月份+类型）。
7. 回复摘要：家庭、月份、类型、用量、费用（总价及分项）、当前档位、本档剩余、截图链接、网站地址、表格链接。

## 同步腾讯文档表格

- 覆盖式更新：`sheet.get_cell_data` 读全表定位键行（家庭+月份+类型），`sheet.set_range_value` 覆盖该行全部 27 列；未找到则写入第一个空行。
- 大表更新分批写入：每批 ≤9 行或 ≤180 cells，避免超限。
- 写入后验证目标行。

## 查询与统计

- 单条查询：`utility.py list --family <名> --month <YYYY-MM> --type <water|electric|gas>`。
- 统计：近 N 月水/电/气用量与费用，环比增减；按年汇总；多家庭按家庭分别汇总勿混算。
- 全量导出 `utility.py dump` 走三表 UNION，统一键名输出（非本费种字段为 null）。

## 用户强调点（必须遵守）

- **水费污水费按用水量90%计收**：污水费=用量×90%×2.00，综合单价=水费单价+污水单价×0.9（第一档4.05元/m³）；tier_detail 分项记录水费价、污水价、污水计费比例、综合价，汇总展示时水费与污水费分项单价都要体现；**水费金额（water_fee）与污水费金额（sewage_fee）必须作为独立分项记录在数据库 bills_water 表与腾讯文档表格第25/26列**。
- **水费总价=水费金额+污水处理费**：与电费总价=峰电费+谷电费概念一致；年度趋势图只画"水费总价"单柱（amount），不得把水费拆成"水费/污水费"两柱；总价分项在月度明细表分列展示、在用能明细堆叠柱分色展示。
- **电费峰谷上期/本期读数在账单是分开的，表格和网页必须分开展示，不得合并**（峰上期/峰本期/谷上期/谷本期四列独立）。
- **明细表格各记录在自己的展示**：水费、电费、燃气费三类账单各自的明细表格与记录必须分开存放与展示——网页按月明细分别渲染水费表（含"水费金额+污水费金额"两列）、电费表（峰谷分项）、燃气表（单价/用量/费用）；数据库按费种拆表（bills_water/bills_electric/bills_gas）各自独立记录，禁止跨类型合并混排。
- **水/电/燃气均分档计费，每档单价不同都要记录**；当前在第几档、本档剩余量都要在网页与表格展示。
- **燃气账单从邮箱下载后**：先导入腾讯文档燃气文件夹（命名带地址）→ 解析 → 记入网页与表格。
- **技能内容更新方式**：每次更新必须**完整读取技能全文、梳理章节顺序后整体重写**，严禁只在末尾追加补丁式内容。

## 常见问题

- 截图里"欠费/预存/余额"不是本期费用，不要记；只记"本期应缴/本月费用"。
- 用量与费用缺失项留空不编造，备注注明。
- 燃气按金额计费无用量时，用量留空、费用必填。
- 截图模糊无法识别 → 如实告知并请用户补发。
- 拆表后 add/update/delete 均按 type 自动路由到对应费种表；dump 三表 UNION，前端字段兼容。
