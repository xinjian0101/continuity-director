# Interface and Localization

This document defines the v0.8 interface rules for Continuity Director.

## Design goals

The interface should feel like a production control panel rather than a collection of unrelated nodes. It must keep high-frequency actions visible, move secondary settings into collapsible sections, and display failures next to the affected field or task.

## Language modes

The interface supports three explicit modes:

| Key | Display name | Behavior |
|---|---|---|
| `en` | English | English-only interface |
| `zh-CN` | 中文 | Simplified Chinese-only interface |
| `bilingual` | English / 中文 | English primary text with Chinese supporting text |

The selected mode should be stored in browser-local settings and restored after ComfyUI reloads.

Language changes must not modify:

- Node type identifiers
- Widget keys
- Workflow JSON keys
- Manifest schema fields
- Stored project data
- API or internal event names

## Recommended layout

```text
┌──────────────────────────────────────────────────────────────┐
│ Continuity Director   Project   Health   Language   Settings │
├──────────────┬──────────────────────────────┬────────────────┤
│ Navigation   │ Main production workspace    │ Inspector      │
│              │                              │                │
│ Dashboard    │ Shot / take / queue / review │ Contextual     │
│ Continuity   │ content                      │ parameters     │
│ References   │                              │                │
│ Batch        │                              │                │
│ Quality      │                              │                │
│ Review       │                              │                │
│ Workers      │                              │                │
├──────────────┴──────────────────────────────┴────────────────┤
│ Task status · warnings · audit events · progress             │
└──────────────────────────────────────────────────────────────┘
```

## Information hierarchy

### Primary navigation

Use stable production concepts instead of implementation terms:

1. Dashboard
2. Continuity
3. References
4. Batch Director
5. Quality Review
6. Collaboration
7. Workers
8. Audit

### Status levels

| Level | Use |
|---|---|
| Ready | Configuration is valid and execution may continue |
| Running | A task is active |
| Attention | User review is required but data is not invalid |
| Blocked | A required condition failed |
| Failed | Execution stopped because of an error |

Do not rely on color alone. Every status must include text and an icon or shape.

## Localization structure

Visible strings should be stored in a central dictionary:

```javascript
export const messages = {
  en: {
    "nav.dashboard": "Dashboard",
    "nav.continuity": "Continuity",
    "action.save": "Save",
    "status.blocked": "Blocked"
  },
  "zh-CN": {
    "nav.dashboard": "控制台",
    "nav.continuity": "连续性",
    "action.save": "保存",
    "status.blocked": "已阻止"
  }
};
```

Bilingual mode should be rendered from the same keys rather than stored as a third duplicated translation set:

```javascript
function formatMessage(key, mode) {
  if (mode === "bilingual") {
    return `${messages.en[key]}\n${messages["zh-CN"][key]}`;
  }
  return messages[mode]?.[key] ?? messages.en[key] ?? key;
}
```

## Component rules

### Buttons

- Start with a verb.
- Use one primary action per panel.
- Disable blocked actions and show the blocking reason.
- Keep destructive actions visually separated.

### Forms

- Put validation text directly below the field.
- Preserve entered values after validation failures.
- Separate required production inputs from optional tuning controls.
- Use advanced collapsible sections for low-frequency parameters.

### Tables and queues

- Keep identifiers, status, owner, revision, and updated time visible.
- Support sorting and filtering without changing the underlying queue order.
- Show task progress and current stage.
- Provide a clear empty state instead of a blank table.

### Notifications

Use inline messages for recoverable validation problems. Use toast notifications only for completed background actions or failures not tied to a visible field.

### Accessibility

- All interactive controls must be keyboard reachable.
- Focus state must remain visible.
- Icon-only buttons require accessible labels and tooltips.
- Text contrast should meet WCAG AA where practical.
- Motion should be limited and nonessential animation should respect reduced-motion settings.

## Persistence and migration

Store only the language key, panel state, and other interface preferences locally. Do not mix interface preferences into workflow files.

Unknown or removed language values must fall back to English without breaking the panel.

## Acceptance checklist

- [ ] English mode contains no unintended Chinese text.
- [ ] Chinese mode contains no unintended English helper text except product names and technical identifiers.
- [ ] Bilingual mode remains readable at common desktop widths.
- [ ] Reloading ComfyUI preserves the selected language.
- [ ] Workflow JSON remains identical after language switching.
- [ ] Missing translation keys fall back safely.
- [ ] Keyboard navigation covers all actions.
- [ ] Error messages identify the affected field or task.
