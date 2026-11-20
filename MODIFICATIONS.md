# OffLook-Modified — changes from the original OffLook-main

> **Historical snapshot — OffLook 0.3.0 development.** This record describes the
> changes and verification at the time, not current behavior. See the current
> [Getting started guide](docs/getting-started.md) and [API reference](docs/api.md).
> OffLook now compares two local files without Git or a repository, and conversion
> uses a dialog with a format dropdown instead of a radial wheel.

## 1. Mouse wheel scrolling, everywhere in both windows

### 1a. Main window (`src/offlook/gui.py`)

Before: the card stack could only be scrolled with the scrollbar on the right.

Now: the wheel scrolls the main window from anywhere inside it — over cards, labels,
buttons, checkboxes and text fields.

- `_bind_mousewheel()` binds `<MouseWheel>` once on the main Toplevel. Binding on the
  toplevel is what makes the gesture reach the whole window: Tk delivers the event to
  the widget under the pointer and then walks up its bindtags to the toplevel.
- `_wheel_main()` converts the Windows `delta` into notches and calls
  `main_canvas.yview_scroll(steps, 'units')`.
  - One notch is `delta = 120`; precision wheels and touchpads send smaller
    multiples, so a partial notch (for example `delta = 30`) still moves one step.
  - **Chained scrolling:** a result table or text box scrolls itself while
    `_can_scroll()` reports hidden content, and *falls through to the page* when it
    does not — so the wheel never appears dead over an empty list.
  - A dropdown keeps its native behaviour, because there the wheel changes the value.
  - The scrollbar is bound directly to `_wheel_main`; returning `"break"` suppresses
    its own four-unit class binding, so it moves exactly as far as the rest.

### 1b. Preview window (`src/offlook/preview/window.py`)

Before: only the text widget (native) and the metadata card scrolled. Pointing at the
header — title, file path field, "Always on top" checkbox — or the footer did nothing.

Now: `PreviewWindow._wheel()` is bound on the preview Toplevel and scrolls the current
body (`self._wheel_target`, set by `_show_text`, `_show_table`, `_show_metadata`)
whenever the pointer is anywhere else in the window. Line-based bodies scroll three
lines per notch, matching Tk's native text binding.

## 2. Stronger visual hierarchy — "what can I click"

`src/offlook/ui/theme.py` was retuned so interactive controls can never be mistaken
for the background:

| Element | Before | Now |
| --- | --- | --- |
| Card surface | white on near-white | white on a cooler grey (`#EDF1F8`) with a 1 px border |
| Buttons | flat, no fill, rim ≈ background | white plate, visible rim (`#9FB0C9`), blue hover fill, darker pressed fill |
| Primary action | blue only on **Choose file** | blue plate with dark border, distinct hover/pressed states |
| Language control | — | segmented 中文 / English, active side filled blue |
| Text fields / dropdowns | thin border | white field, 1 px rim, blue rim while focused, blue dropdown arrow |
| Scrollbars | very light | visible trough and thumb, darker thumb on hover |
| Result tables | borderless | 1 px rim, tinted heading, readable selection colour |

## 3. Chinese / English interface switch

- New module `src/offlook/ui/i18n.py`: one table of ~150 keys holding the English and
  Chinese text side by side, `tr()` for the active language, `tr_in()` for a specific
  language, `set_language()`, `normalize_language()`, plus `missing()` used by tests to
  prove no key is untranslated.
- New configuration field `language` (`"en"` default, `"zh"`); validated in
  `core/config.py`, saved to the same JSON file as the other settings, so the choice
  survives a restart.
- **Top-right segmented control** with a `中文` and an `English` button, next to Help.
  Clicking one saves the setting and rebuilds the main window immediately.
- Rebuild strategy: every value lives in an instance `StringVar`, so typed paths,
  AI settings, shortcut drafts and live results survive the rebuild; cached search and
  filter rows are re-inserted, and prompts are re-rendered in the new language while
  real messages (errors, counts) are left untouched.
- Translated surfaces: main window (cards, buttons, hints, statuses, hotkey states),
  preview window (header, footer, metadata card), Help window (full Chinese text),
  conversion wheel, and the Git comparison window.
- Core `OffLookError` messages stay in English on purpose: they quote file-system and
  configuration details, and the GUI shows them verbatim.

## 4. Fixed the crash that stopped the main window from opening (inherited bug fix)

`gui.py` created the Quality dropdown with `ttk.Combobox(..., command=...)`, but
`ttk::combobox` has no `-command` option, so building the window raised
`TclError: unknown option "-command"`. Fixed by binding `<<ComboboxSelected>>`
instead and giving `_convert_mode_changed(self, _event=None)` the event parameter.
Side effect: changing **Quality** now actually saves the new mode.

## 6. Restored the teammate's preview zoom controls

This build started from a **ZIP snapshot** of the repository. A teammate pushed

```
9ebdc77  Add manual zoom controls to preview window
```

after that snapshot, so copying our tree over the clone replaced
`src/offlook/preview/window.py` and **silently removed that feature**
(`git grep zoom HEAD` returned nothing).

The feature is now merged into our version and integrated with the wheel work:

| Part | Behaviour |
| --- | --- |
| `_zoom` | 100% start, 25%–400% range, ±25% per click |
| `+` / `−` | Re-requests a higher-resolution raster through `bounded_viewport`, so magnifying reveals real pixels instead of stretching the old image |
| `Fit` | Back to 100%; the label is translated (`Fit` / `適應`) |
| Image canvas | When zoomed past the window, the image pans with the wheel or the scrollbars (it shares `_wheel_target` with section 1b) |
| Navigation bar | Now shown for PDFs *and* images; the zoom controls hide for text and tables |

**Files**: `src/offlook/preview/window.py`, `src/offlook/ui/i18n.py`
**Verification**: 11 checks (controls visible, percentage, larger raster, cap, scrollregion, wheel panning, Fit reset, hidden for text).

**Process lesson**: a ZIP download contains no Git history. Clone the repository
first and edit in the clone; do not copy a ZIP snapshot over it, since that can
remove teammates' changes.

## 7. Documentation updated

- `README.md` — language-switch bullet under *Main controls*.
- `docs/api.md` — `language` configuration field.
- `pyproject.toml` — version `0.3.0`, description marks the modified build.

## Verification performed at the time

- `python -m compileall` on `src`: clean.
- Language switching test: English window → Chinese window → back, 69 labels inspected
  each time, no untranslated key (`i18n.missing("zh")` is empty), settings persisted to
  the JSON file, search-filter labels and Help body switch too, and a live status
  message is *not* overwritten by the retranslation pass.
- Real mouse-wheel test (12 cases, real `mouse_event` with the pointer verified through
  `winfo_containing`) — see section 1.
- Visual checks used four screenshots. The [English main window](docs/images/main-window-en.png),
  [Chinese main window](docs/images/main-window-zh.png), and [Chinese Help](docs/images/help-zh.png)
  paths now point to current screenshots. The [Chinese metadata preview](docs/images/preview-zh.png)
  is retained as a historical screenshot.
- Application start-up retested after every change; the process stays alive and the
  window renders.
