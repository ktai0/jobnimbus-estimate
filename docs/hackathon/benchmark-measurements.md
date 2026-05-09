# Benchmark Measurements

Two sets of properties.

- **Example Properties (5):** reference data shown for calibration. We are NOT scoring you on these.
- **Test Properties (5):** addresses only. **These are what you submit results for.** Run your tool on all 5; submit total sqft for each via the [submission form](./SUBMISSION.md).

For each example property below, two trusted reference measurements are shown — labeled simply as **Reference A** and **Reference B**. They serve as trusted reference points, though commercial measurement products can vary in their methodology and what line items they report. Submissions will be judged for **practical accuracy and consistency** across the test properties — not exact matching.

---

## Example Properties — *calibration references only*

> These properties are provided so you can validate your tool. **They are not the addresses you'll be scored on.** Use them to confirm your pipeline produces reasonable numbers before you run on the test set. Note that the two references don't always agree on every line item — that's normal, and reflects the natural variance between commercial measurement products.

### 1. 21106 Kenswick Meadows Ct, Humble, TX 77338

| Source | Total sqft | Pitch |
|---|---|---|
| Reference A | 2,443 | 6:12 |
| Reference B | 2,343 | 6:12 |

**Reference A line items:** Ridge/Hip: 141 · Valleys: 40 · Rakes: 101 · Eaves: 187 · Flashing: 27 · Step Flashing: 21
**Reference B line items:** Ridge: 26 · Hip: 101 · Valley: 38 · Rake: 83 · Eave: 90 · Gutter: 74 · Flashing: 25 · Total Eaves: 164

### 2. 5914 Copper Lilly Lane, Spring, TX 77389

| Source | Total sqft | Pitch |
|---|---|---|
| Reference A | 4,391 | 8:12 |
| Reference B | 4,296 | 8:12 |

**Reference A line items:** Ridge: 79 · Hip: 321 · Valleys: 197 · Rakes: 121 · Eaves: 324 · Flashing: 51 · Step Flashing: 94
**Reference B line items:** Ridge: 77 · Hip: 348 · Valley: 195 · Rake: 119 · Eave: 220 · Gutter: 73 · Step Flashing: 92 · Total Eaves: 293

### 3. 122 NW 13th Ave, Cape Coral, FL 33993

| Source | Total sqft | Pitch |
|---|---|---|
| Reference A | 2,917 | 6:12 |
| Reference B | 2,851 | 6:12 |

**Reference A line items:** Ridge: 59 · Hip: 83 · Valleys: 22 · Rakes: 51 · Eaves: 201 · Flashing: 1 · Step Flashing: 19
**Reference B line items:** Ridge: 59 · Hip: 81 · Valley: 21 · Rake: 49 · Eave: 148 · Gutter: 50 · Step Flashing: 17 · Total Eaves: 198

### 4. 14132 Trenton Ave, Orland Park, IL 60462

| Source | Total sqft | Pitch |
|---|---|---|
| Reference A | 2,990 | 4:12 |
| Reference B | 2,935 | 4:12 |

**Reference A line items:** Ridge/Hip: 241 · Valleys: 78 · Rakes: 0 · Eaves: 255
**Reference B line items:** Ridge: 48 · Hip: 187 · Valley: 78 · Rake: 0 · Gutter: 251 · Step Flashing: 10 · Total Eaves: 251

### 5. 835 S Cobble Creek, Nixa, MO 65714

| Source | Total sqft | Pitch |
|---|---|---|
| Reference A | 3,070 | 8:12 |
| Reference B | 3,017 | 8:12 |

**Reference A line items:** Ridge/Hip: 232 · Valleys: 113 · Rakes: 50 · Eaves: 211
**Reference B line items:** Ridge: 79 · Hip: 150 · Valley: 111 · Rake: 48 · Gutter: 208 · Step Flashing: 4 · Unset: 49

---

## Test Properties (no benchmark data — these are what you submit)

Run your tool on all 5. Submit total sqft for each via the [submission form](./SUBMISSION.md):

1. **3561 E 102nd Ct, Thornton, CO 80229**
2. **1612 S Canton Ave, Springfield, MO 65802**
3. **6310 Laguna Bay Court, Houston, TX 77041**
4. **3820 E Rosebrier St, Springfield, MO 65809**
5. **1261 20th Street, Newport News, VA 23607**

Submit by **Saturday 1:30 PM**.

---

## What we judge on accuracy

Your total sqft for each test property is evaluated against trusted reference measurements with reasonable tolerance. **Your tool will be judged on practical accuracy and consistency across all properties, not exact matching.**

If you want to gut-check before submitting: run your tool on the example properties above and compare your totals to the reference values. Consistent results across the example set are a good signal.

> **One important note on roof area vs. footprint:** The square footage you report should be **roof area** (footprint × pitch multiplier), not the building footprint area. Reference measurements report roof area; if your tool returns footprint, you'll be roughly 5–20% under depending on pitch. Common bug, easy to get right.
