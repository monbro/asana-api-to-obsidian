# Subtask Format Comparison

## Old Format (Collapsible HTML)
```html
<details>
<summary>☐ <strong>Design Website Mockup</strong></summary>

📅 **Due**: 2024-03-15 | 👤 **Assigned to**: John Doe | 📌 **Sub-subtasks**: 3

**Details:**
- **Created**: 2024-03-01
- **Modified**: 2024-03-10
- **Assignee Status**: upcoming
- **Asana ID**: `123456789`
- **Link**: [Open in Asana](https://app.asana.com/...)

Create initial mockups for the homepage and main sections.

<details>
<summary>Raw Asana Data (JSON)</summary>
...
</details>

**Sub-subtasks:**
  <details>
  <summary>☐ <strong>Hero Section</strong></summary>
  ...
  </details>

</details>
```

**Problems with old format:**
- Content is hidden until you click to expand
- Formatting and structure not immediately visible
- Hard to scan through multiple subtasks
- Requires interaction to see details
- Not searchable when collapsed

---

## New Format (Readable Markdown)

### ⏳ Design Website Mockup

📅 **Due**: 2024-03-15 | 👤 **Assigned to**: John Doe | 🟢 **Start**: 2024-03-01 | 📊 **Status**: upcoming | 📌 **Sub-subtasks**: 3

> Create initial mockups for the homepage and main sections.

| Field | Value |
|-------|-------|
| Created | 2024-03-01 10:30:00 |
| Modified | 2024-03-10 14:20:00 |
| Assignee Status | upcoming |
| Task Type | design |
| Asana ID | `123456789` |
| Link | [Open in Asana](https://app.asana.com/...) |

#### Sub-subtasks

##### ⏳ Hero Section

📅 **Due**: 2024-03-08 | 👤 **Assigned to**: Jane Smith

> Design the hero section with call-to-action button.

| Field | Value |
|-------|-------|
| Created | 2024-03-01 10:35:00 |
| Modified | 2024-03-05 09:15:00 |
| Asana ID | `123456790` |

##### ✅ Navigation Menu

📅 **Due**: 2024-03-07 | 👤 **Assigned to**: Jane Smith

> Create navigation menu design with all main sections.

| Field | Value |
|-------|-------|
| Created | 2024-03-01 10:36:00 |
| Completed | 2024-03-06 16:45:00 |
| Completed by | Jane Smith |
| Asana ID | `123456791` |

---

## Benefits of New Format

✅ **Immediately Visible**: All content is visible without expanding
✅ **Better Hierarchy**: Clear header levels (###, ####, etc.) show task relationships
✅ **Scannable**: Easy to scan through all subtasks at once
✅ **Searchable**: All text is searchable in Obsidian
✅ **Better Formatting**: Proper markdown tables, blockquotes, and structure
✅ **Status at a Glance**: Emoji indicators (⏳ pending, ✅ completed) are visible immediately
✅ **Metadata Organized**: Clean tables make information easy to find
✅ **Obsidian-Friendly**: Works perfectly with Obsidian's markdown rendering
✅ **No Interaction Needed**: All information available without clicking

## Key Changes

1. **Headers instead of `<details>`**: Uses `###`, `####` for proper hierarchy
2. **Visible Status**: Checkboxes (⏳/✅) in headers instead of hidden in collapsed sections
3. **Blockquotes for Descriptions**: Makes descriptions stand out visually
4. **Clean Tables**: Metadata in readable markdown tables
5. **Proper Nesting**: Sub-subtasks use increasing header levels (###, ####, #####)
6. **No Collapsing**: Everything is visible for maximum usability

The files may be longer now, but they're much more usable and the data is properly accessible!
