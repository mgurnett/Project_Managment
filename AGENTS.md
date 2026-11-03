AGENTS.md
Convert Technical Documentation into a Veriqta-Style Visual Cheat Sheet

## Objective
Transform the provided markdown, runbook, or technical notes into a self-contained, print-ready HTML/CSS single-sheet reference card modeled on technical production field guides (Veriqta style).

## Design & Layout Specifications
1. Grid Structure:
   - Use a strict CSS Grid layout (`grid-template-columns: 1fr 1fr; gap: 10px;`).
   - Standard panels take 1 column. High-density overview tables (like node inventories or architectural overviews) must take full width (`grid-column: span 2;`).
   - Page dimensions must target standard Letter portrait (`@page { size: letter portrait; margin: 8mm; }`).

2. Visual Hierarchy & Styling:
   - Header: Bold banner at the top with an uppercase small-caps category badge, a prominent 22-24px display title, a subtitle bar, and a right-aligned host/environment info box.
   - Cards: Crisp borders (`1px solid #e2e8f0`), rounded corners (`6px`), white background, and `break-inside: avoid;` to prevent awkward print splits.
   - Numbered Badges: Every card header must start with a small, circular numbered badge (`width: 18px; height: 18px; border-radius: 50%; background: #0284c7; color: #fff; font-size: 10px; font-weight: 800;`).
   - Typography: Clean sans-serif for UI (`Inter`, system-ui) and monospace (`Fira Code`, `JetBrains Mono`) for commands and data tables.
   - Colors: Slate/Navy neutral base (`#0f172a`, `#64748b`) with a primary accent (e.g., `#0284c7` blue) and small pill status tags (green, blue, amber).

3. Content Formatting:
   - Tables: Compact, border-collapsed tables with uppercase column headers on subtle gray backgrounds.
   - Terminal Blocks: Dark slate container (`background: #0f172a; color: #e2e8f0;`) with distinct colors for commands (`#38bdf8`) and comments (`#64748b`). Keep commands concise and realistic.
   - Bullet Points: Custom colored dot (`content: "•"; color: #0284c7;`) with inline bold keywords.

## Critical Output Rules
- Single, Self-Contained Deliverable: Return ONLY the raw, complete, and un-truncated HTML file with inline `<style>`. Never omit closing tags (`</div>`, `</body>`, `</html>`).
- Print Safety: Always include `-webkit-print-color-adjust: exact;` and `print-color-adjust: exact;` in the body CSS so backgrounds and badges render when saving to PDF.
- PDF Command: At the end, output the headless Chrome print command using `--no-pdf-header-footer` so no browser URLs or timestamps appear on the PDF.

HUMAN NOTES:

When asked to doa write up, please produce it in this style with the accompning PDF command at the end.
I would like to be able to easily reference this later, so please make it look nice.
I am including this file so that you may reference it when I ask for a write up.
These do not need to be limited to a single sheet.  Use as many sheets as you need to make it look nice.

Only produce documentation when the user askes you to.