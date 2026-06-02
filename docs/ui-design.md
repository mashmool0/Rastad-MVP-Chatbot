# UI Design — Rastad AI Assistant

## Pages Overview

| Route | Auth | Description |
|---|---|---|
| `/` | Required | Main chat + inspector page |
| `/login` | Open | Username + password form |
| `/signup` | Open | Username + name + password x2 form |

---

## Main Page `/`

Single page, desktop-first, Tailwind CSS via CDN.
Two-column layout — chat on the left, inspector on the right.

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────┐
│  🤖 Rastad AI Assistant              [خروج]   سلام، {name}          │  ← navbar
├──────────────────────────────┬──────────────────────────────────────┤
│                              │                                      │
│      CHAT PANEL              │        INSPECTOR PANEL               │
│      (left — 55%)            │        (right — 45%)                 │
│                              │                                      │
│  ┌────────────────────────┐  │  ┌──────────────────────────────┐   │
│  │   تاریخچه پیام‌ها       │  │  │  آخرین تحلیل                │   │
│  │                        │  │  │                              │   │
│  │  [user bubble]         │  │  │  intent:                     │   │
│  │  [assistant bubble]    │  │  │  ┌──────────────────────┐    │   │
│  │  [user bubble]         │  │  │  │  vip_question         │    │   │
│  │  [assistant bubble]    │  │  │  └──────────────────────┘    │   │
│  │                        │  │  │                              │   │
│  │                        │  │  │  segment:                    │   │
│  │                        │  │  │  ┌──────────────────────┐    │   │
│  └────────────────────────┘  │  │  │  vip_interest         │    │   │
│                              │  │  └──────────────────────┘    │   │
│  ┌────────────────────────┐  │  │                              │   │
│  │  پیام خود را بنویسید...│  │  │  needs_human_support:        │   │
│  │                   [→]  │  │  │  ┌──────────────────────┐    │   │
│  └────────────────────────┘  │  │  │  ❌ False              │    │   │
│                              │  │  └──────────────────────┘    │   │
│                              │  │                              │   │
│                              │  │  confidence:                 │   │
│                              │  │  ┌──────────────────────┐    │   │
│                              │  │  │  █████████░  0.82     │    │   │
│                              │  │  └──────────────────────┘    │   │
│                              │  │                              │   │
│                              │  │  chunks used:                │   │
│                              │  │  · vip_products.txt §2       │   │
│                              │  │  · rastad_services.txt §1    │   │
│                              │  │                              │   │
│                              │  │  latency: 1380ms             │   │
│                              │  │  llm: openrouter             │   │
│                              │  │  fallback: no                │   │
│                              │  │                              │   │
│                              │  │  ┌──────────────────────┐    │   │
│                              │  │  │  {} نمایش JSON کامل   │    │   │
│                              │  │  └──────────────────────┘    │   │
│                              │  └──────────────────────────────┘   │
│                              │                                      │
└──────────────────────────────┴──────────────────────────────────────┘
```

---

## Chat Panel (Left)

### Message history area
- Scrollable list of past messages for the current session
- **User bubble**: right-aligned, dark background, white text
- **Assistant bubble**: left-aligned, light background, dark text, rastad logo/icon
- Newest message scrolls into view automatically
- Empty state: a centered prompt ("اولین سوال خود را بپرسید")

### Input area (bottom, sticky)
- `<textarea>` — right-to-left, Persian placeholder: `پیام خود را بنویسید...`
- Send button (→ icon) — right side of input
- Submit on Enter key (Shift+Enter for new line)
- Input disabled + spinner shown while waiting for response
- On submit: message appears immediately as user bubble, then assistant bubble appears when response arrives

### User identity
- `user_id` is read from session (set after login) — not shown to user, sent silently with API call
- `name` is shown in the navbar greeting only

---

## Inspector Panel (Right)

Updates on every message response. Shows data from the last API call.
Purpose: give the evaluator (کارفرما) full visibility into the AI decision without reading logs.

### Sections

**intent** — colored badge
- `vip_question` → purple badge
- `exchange_registration` → blue badge
- `kol_collaboration` → green badge
- `support_request` → red badge
- `general_info` → gray badge
- `unknown` → yellow badge

**segment** — colored badge (same color logic per segment type)

**needs_human_support** — boolean indicator
- `False` → ❌ red pill "نیاز به انسان: خیر"
- `True` → ✅ green pill "نیاز به انسان: بله" (with pulsing dot)

**confidence** — progress bar
- Value: top KB similarity score (0.0 → 1.0)
- Color: green (> 0.7), yellow (0.45–0.7), red (< 0.45)
- Label: HIGH / MEDIUM / LOW

**chunks used** — list
- Source file name + chunk index for each retrieved KB chunk
- e.g. `vip_products.txt §2`, `rastad_services.txt §1`
- Max 4 items

**metadata row** — small muted text
- `latency: 1380ms` · `llm: openrouter` · `fallback: خیر`

**JSON toggle button** — "نمایش JSON کامل"
- Expands/collapses a `<pre>` block with the full raw response JSON
- Useful for the evaluator to copy and inspect the exact output
- Syntax-highlighted with a monospace font

---

## Login Page `/login`

Minimal, centered card. Tailwind card component.

```
┌──────────────────────────────┐
│        🤖 راستاد              │
│                              │
│  نام کاربری                  │
│  ┌────────────────────────┐  │
│  │                        │  │
│  └────────────────────────┘  │
│                              │
│  رمز عبور                    │
│  ┌────────────────────────┐  │
│  │                        │  │
│  └────────────────────────┘  │
│                              │
│  ┌────────────────────────┐  │
│  │       ورود              │  │
│  └────────────────────────┘  │
│                              │
│  حساب ندارید؟  ثبت‌نام        │
└──────────────────────────────┘
```

- Error message shown inline (username/password wrong)
- RTL form, Persian labels
- Link to `/signup` at bottom

---

## Signup Page `/signup`

Same card style as login, with four fields:

1. نام کاربری (username)
2. نام نمایشی (name — stored as `RastadUser.name`)
3. رمز عبور (password)
4. تکرار رمز عبور (password confirmation)

- Client-side: confirm passwords match before submit
- Server-side: DRF/Django form validation, duplicate username error shown inline
- On success: redirect to `/login` with a success banner

---

## Technical Notes

- **Tailwind CSS**: loaded via CDN — no build step, no Node.js required
- **RTL**: `<html dir="rtl" lang="fa">` — all text and layout right-to-left
- **Font**: Vazirmatn (Google Fonts or CDN) — best Persian web font, free
- **AJAX**: chat panel uses `fetch()` to `POST /api/message` without page reload
- **CSRF**: Django CSRF token included in fetch headers (`X-CSRFToken`)
- **No framework**: plain HTML + Tailwind + vanilla JS — no React, no Vue
- **Responsive**: desktop-first — two columns on ≥ 1024px, single column stack on mobile (not the focus)
- **Templates**: Django template engine, extends a `base.html` with shared head/navbar
