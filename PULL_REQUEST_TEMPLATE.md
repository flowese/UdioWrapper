# NoPechA hCaptcha Auto-Solve Integration

## 🎯 Problem Solved

Udio introduced hCaptcha protection in April 2024, which broke the original API-based approach. Multiple contributors have struggled with manual Selenium workarounds that still require frequent manual intervention.

### Solution
- Integrates NoPechA API for automated hCaptcha solving
- Provides **Hybrid mode**: tries direct API first, automatically falls back to browser automation when hCaptcha is detected
- Supports both synchronous and asynchronous APIs

---

## 🔧 Features Added

1. **`nopecha_client.py`** - General-purpose NoPechA client with retry logic
2. **`udio_wrapper_hybrid.py`** - Extended UdioWrapper with auto-fallback
3. **Configuration Options** - Easy setup via environment variables

---

## 💰 Cost Analysis

| Metric | Value |
|--------|-------|
| NoPechA Pricing | $1 = ~90,000 solutions |
| Cost per solve | ~$0.000011 |
| Estimated usage (10 songs/day) | ~$0.007/month |

Even heavy usage costs less than 1 cent per month!

---

## ✅ Testing

Quick test:
```bash
python udio_wrapper_hybrid.py
```

Expected output:
```
✓ Auth token found
Creating test song...
✅ Generated 2 tracks!
```

---

## 🙏 Acknowledgments

- Flowese (original UdioWrapper author)
- jfarre20 (extensive Selenium research in Issue #7)
- Pikachubolk (NoPechA integration inspiration)

---

## 📋 Related Issues

Fixes: #7 (500 Server Error - Auto Solve hcapcha)
