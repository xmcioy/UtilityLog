# Changelog

All notable changes to this project will be documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 规划（0.2）
- 多用户注册/登录，账单按用户隔离
- 每用户 API Token，供 Skill 远程录入
- 设置页：通用模型 API 配置 + 用户模型 Token
- 网页端图片/文字直接上传录入（配模型 API 自动解析）
- 手工编辑/删除账单入口

## [0.1.0] - 2026-10-24

### 新增
- 项目开源化：源码（CLI 脚本 + 认证网关 + 网页）、文档、技能统一收纳
- `docs/DESIGN.md` 设计文档：表结构、程序逻辑、展示设计、多用户规划
- `db/schema.sql` 建表语句（含 0.2 多用户规划表）
- `skill/SKILL.md` 记录技能（脱敏模板版，敏感信息以占位符代替）
- README 中英文双语说明；传统命令安装 + AI 客户端（Codex / WorkBuddy）指令安装两种方式
- CHANGELOG 修订记录体系从本版本开始

### 变更
- 认证网关凭据由硬编码改为环境变量 / 配置文件读取（仓库内不含真实凭据）
- CLI 脚本路径由绝对路径改为基于项目根的自动推导，支持 `UL_ROOT` 环境变量覆盖

### 说明
- 本仓库为开源发布版，不包含任何本地私有记录（账单数据、账单截图、腾讯文档 ID、邮箱、地址、域名等均不入库）
