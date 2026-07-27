# Model Settings Page Overrides

> **PROJECT:** Financial Skill Platform
> **Generated:** 2026-07-27 14:20:33
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** 1. Hero (product + live preview or status), 2. Key metrics/indicators, 3. How it works, 4. CTA (Start trial / Contact)

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** 浅色中性表面。蓝色用于主操作，绿色/琥珀色/红色仅用于状态。

### Component Overrides

- No overrides — use Master component specs

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- API Key 输入始终使用可见标签、明文切换按钮和提交加载状态。
- 连接卡片优先展示供应商、脱敏密钥、连接状态和默认模型。
- 删除连接使用二次确认；动态结果通过 `aria-live` 通知。
