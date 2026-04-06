# UdioWrapper - NoPechA hCaptcha Auto-Solve Integration

> **[Original UdioWrapper](https://github.com/flowese/UdioWrapper)** | **[Issue #7 - hCaptcha Problem](https://github.com/flowese/UdioWrapper/issues/7)**

This enhanced version adds **automatic hCaptcha solving** to bypass Udio's anti-bot protection.

## ⚡ Quick Start

### 1. Installation

```bash
pip install requests aiohttp playwright
playwright install chromium
```

### 2. Configure Environment Variables

```bash
export UDIO_AUTH_TOKEN="your_sb-api-auth-token"
export NOPECHA_API_KEY="your_nopecha_key"
```

Get NoPechA key from: https://nopecha.com/pricing (~$0.007/month)

### 3. Use in Your Code

```python
from udio_wrapper_hybrid import UdioWrapperHybridSync

client = UdioWrapperHybridSync(
    auth_token=os.getenv("UDIO_AUTH_TOKEN"),
    nopecha_api_key=os.getenv("NOPECHA_API_KEY")
)

result = client.create_with_fallback_sync("relaxing jazz music")
print(result)
```

---

## 🔍 How It Works

1. **Try Direct API** - Fast path when no captcha
2. **Detect hCaptcha** - Automatically if 500 error detected
3. **Switch to Browser** - Headless Playwright + NoPechA auto-solve
4. **Inject Token** - Seamlessly continue generation

---

## 💰 Cost Breakdown

- **NoPechA**: $1 = ~90,000 solutions
- **Per solve**: ~$0.000011
- **Monthly** (heavy use): <$0.10

---

## 📚 Documentation

- `README_HYBRID.md` - This guide
- `PULL_REQUEST_TEMPLATE.md` - PR template
- `nopecha_client.py` - SDK documentation
- `udio_wrapper_hybrid.py` - Hybrid mode docs

---

## 🤝 Contributing

Inspired by community research in Issue #7. Contributions welcome!

---

**Ready to generate music again!** 🎵
