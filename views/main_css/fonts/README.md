# Distorted face fallback

`noto-distorted-face.woff2` contains only U+1FAEA (distorted face), with its
COLRv1 color layers. CSS restricts this font to that code point; other text
keeps the existing font stack. No operating-system font installation is needed.

- Source: [Google Noto Emoji, Noto-COLRv1.ttf](https://github.com/googlefonts/noto-emoji/blob/06121655d0e82f9cae6e7ba6feed4fa6fdbfc2a4/2D/fonts/Noto-COLRv1.ttf)
- Revision: `06121655d0e82f9cae6e7ba6feed4fa6fdbfc2a4`
- Copyright: 2022 Google Inc. (retained in the font's name table).
- License: SIL Open Font License 1.1, copied unchanged to [OFL.txt](OFL.txt)
  from the same revision's `2D/fonts/LICENSE`.
- Modification: single-code-point WOFF2 subset using FontTools 4.60.1.
- Source SHA-256: `b8e25ea68db82f9e4d0aee921f4420be2be39887bd5c893a2ad98710531f9d0c`
- Subset SHA-256: `1dc51a9251bb4d63a84c6cd4f813fe69569a98f7808fcc825b557fcdb4792311`
- Subset size: 1,148 bytes; 11 glyphs including required color-layer outlines.

Rebuild from the repository root in PowerShell (requires `uv`; no project
dependencies are added):

```powershell
$fontSource = Join-Path $env:TEMP 'ishs-Noto-COLRv1-06121655.ttf'
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/googlefonts/noto-emoji/06121655d0e82f9cae6e7ba6feed4fa6fdbfc2a4/2D/fonts/Noto-COLRv1.ttf' -OutFile $fontSource
uv run --with 'fonttools[woff]==4.60.1' pyftsubset $fontSource --unicodes=U+1FAEA --flavor=woff2 --output-file=views/main_css/fonts/noto-distorted-face.woff2 --no-recalc-timestamp
```

Verify the subset's only encoded character and color format:

```powershell
uv run --with 'fonttools[woff]==4.60.1' python -c "from fontTools.ttLib import TTFont; f = TTFont('views/main_css/fonts/noto-distorted-face.woff2'); assert set(f.getBestCmap()) == {0x1FAEA}; assert f['COLR'].version == 1; assert 'CPAL' in f; print('U+1FAEA COLRv1 subset OK')"
```
