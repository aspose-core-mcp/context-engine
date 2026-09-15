# Admin console fonts

The admin console ships its fonts from this directory, so building it downloads no fonts.
Both families are in the public domain: they may be used, modified, bundled, redistributed
and sold, in open-source and commercial products alike, with no license terms, fees or
attribution requirements.

| Directory | Family | Status | Used for |
|-----------|--------|--------|----------|
| [`tuffy/`](tuffy) | Tuffy 1.28 by Thatcher Ulrich, Karoly Barta and Michael Everson | Public domain | Interface text (`--font-tuffy`) |
| [`nk57-monospace/`](nk57-monospace) | NK57 Monospace 1.001 by Ray Larabie, Typodermic Fonts | CC0 1.0 Universal | Identifiers, code and numbers (`--font-nk57`) |

Both families cover Latin, Greek and Cyrillic, so the English and Russian interfaces render
in the same typefaces. [`src/app/layout.tsx`](../app/layout.tsx) registers them with
`next/font/local`, and [`src/theme/mono.css`](../theme/mono.css) maps them to the
`--font-sans`, `--font-display` and `--font-mono` tokens.

## Tuffy

- **Source:** [tulrich.com/fonts](https://tulrich.com/fonts/), archive `tuffy-20120614.zip`
  (SHA-256 `9cee853bca685268f3764e8c9373c761bbd0e2862df4b23742f38472da323204`). Its font
  files are byte-identical to those in the Debian `fonts-tuffy` 20120614 source package.
- **Dedication**, from the archive's `LICENSE.txt`:

  > We, the copyright holders of this work, hereby release it into the public domain. This
  > applies worldwide.
  >
  > In case this is not legally possible,
  >
  > We grant any entity the right to use this work for any purpose, without any conditions,
  > unless such conditions are required by law.

  Each font file repeats it: "This font, including hint instructions, has been donated to
  the Public Domain."

| File | CSS weight | Converted from | Source SHA-256 |
|------|------------|----------------|----------------|
| `Tuffy-Regular.woff2` | 400 | `Tuffy.ttf` | `b97cd5005278b24aabb69b8b6ead98860955599558f6e8119483b575a5fdce98` |
| `Tuffy-Italic.woff2` | 400 italic | `Tuffy_Italic.ttf` | `94313dc6018e1f9b39aec9c9e4dd7e603320d47d7b1f30ea24e111d7b9ef2fb6` |
| `Tuffy-Bold.woff2` | 700 | `Tuffy_Bold.ttf` | `ead68ba8bef71d5f6411f2a585dca28a15dc7e5b7729fd64b9faff05730ddfde` |
| `Tuffy-BoldItalic.woff2` | 700 italic | `Tuffy_Bold_Italic.ttf` | `49b937a107d72fa2cbb8dee672c1fb052c6d50eb627d2461339ac1b697caf620` |

## NK57 Monospace

- **Source:** [typodermicfonts.com/public-domain](https://typodermicfonts.com/public-domain/),
  archive `nk57-monospace.zip`
  (SHA-256 `ca93ed45325de31a8d0b44ac1177ba372ac48ef019ea8101edfd8a108a0cc831`), normal-width
  styles.
- **Dedication:** Typodermic Fonts released the family under
  [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/), and each font file
  records "Released in 2024 under CC0 license. No rights reserved." CC0 waives copyright
  only: it grants no trademark rights, so do not use the Typodermic name to suggest
  endorsement.

| File | CSS weight | Converted from | Source SHA-256 |
|------|------------|----------------|----------------|
| `NK57Monospace-Book.woff2` | 400 | `NK57 Monospace No Bk.otf` | `00f0666c55fdf23066ce73f1519b0968e8adf8bbcc7fa0bb062e62587a662a69` |
| `NK57Monospace-BookItalic.woff2` | 400 italic | `NK57 Monospace No Bk It.otf` | `cd7450310ada173c36015f6cbbc4d9221d92c850482d26a4c12859cfacdf7e92` |
| `NK57Monospace-Regular.woff2` | 500 | `NK57 Monospace No Rg.otf` | `89230a04f2de6a7d1f98d6a4e74c6b1f743d4e25a9ac8108666b991bcfb62098` |
| `NK57Monospace-RegularItalic.woff2` | 500 italic | `NK57 Monospace No Rg It.otf` | `6f3c878322910c05f47dcc6e2aac5fc81bbace44c3efa464220b8841b3e9e6ed` |
| `NK57Monospace-SemiBold.woff2` | 600 | `NK57 Monospace No Sb.otf` | `eeed1db8a31c5563567e476fb86b4798ba3f12b59516f9488d7116cd1f1556d6` |
| `NK57Monospace-SemiBoldItalic.woff2` | 600 italic | `NK57 Monospace No Sb It.otf` | `cb00e61afa155a0aa5287a6321195d809a20d05522cec99409df393abd36f1d0` |

The family's Book and Regular styles both declare OS/2 weight 400, but their stems step
evenly from Light to ExtraBold, so Book maps to CSS weight 400 and Regular to 500.

## Conversion

The WOFF2 files were converted with [fontTools](https://github.com/fonttools/fonttools)
without subsetting, so outlines, hinting, metrics, kerning and character maps are unchanged.
The conversion drops the NK57 `DSIG` signature table, which any change of container
invalidates.

```bash
pip install fonttools brotli
python -c 'import sys; from fontTools.ttLib import TTFont; f = TTFont(sys.argv[1], recalcTimestamp=False); f.flavor = "woff2"; f.save(sys.argv[2])' Tuffy.ttf Tuffy-Regular.woff2
```

Only the weights the console uses are included, each with its italic. Tuffy has no style
between Regular and Bold, so CSS weights 500 and 600 render with the nearest of the two. To
add a style, take it from the same archive, check the archive checksum, convert it the same
way and register it in `layout.tsx`.
