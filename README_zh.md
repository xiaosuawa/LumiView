<p align="center">
  <h1 align="center">LumiView</h1>
  <p align="center">
    <strong>Pythonic 的 WebView 桌面App开发框架 — 轻量、开箱即用、异步优先。</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/lumiview/"><img src="https://img.shields.io/pypi/v/lumiview?label=pypi" alt="PyPI"></a>
    <a href="https://pypi.org/project/lumiview/"><img src="https://img.shields.io/pypi/pyversions/lumiview" alt="Python versions"></a>
    <a href="https://github.com/xiaosuawa/LumiView/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/lumiview" alt="License: MPL-2.0"></a>
  </p>
  <p align="center">
    <a href="README.md">English</a>
  </p>
</p>

---

> ⚠️ **早期开发阶段 — API 可能变动**
>
> LumiView 目前处于**早期alpha**阶段。API 已可用但**尚未稳定**——方法名、参数结构、导入路径都可能在 dev 版本间调整。我们通过 dev 版本收集早期反馈，同时保留灵活调整 API 的权利。
>
> **欢迎早期体验者！** 尝试用它构建应用，然后告诉我们哪里好用、哪里不好用。你的反馈将直接塑造最终的稳定 API。升级时请关注变更日志并做好调整代码的准备。

---

## LumiView 是什么？

LumiView 是一个专注于系统 WebView 的 App 开发框架。底层封装了 [tao](https://github.com/tauri-apps/tao) 和 wry (基于 [wryview](https://github.com/xiaosuawa/wryview))，上层提供简洁开箱即用的 async-first Python API 。

### 架构

```mermaid
flowchart TB
    subgraph py["Python 层"]
        direction LR
        App ~~~ Window ~~~ Bridge ~~~ Task["Task[T]"] ~~~ Serve
    end

    subgraph rust["Rust 层 (PyO3)"]
        TaoWindow ~~~ EventLoop
    end

    subgraph plat["平台 WebView"]
        direction LR
        Win["Windows: WebView2"] ~~~ Mac["macOS: WKWebView"] ~~~ Linux["Linux: WebKitGTK"]
    end

    py --> rust --> plat
```

**线程模型：** 主线程（事件循环 + 原生操作）→ 异步线程（asyncio + 用户协程）→ 线程池（同步代码）。

## 安装

```bash
pip install --pre lumiview
```

## 快速开始

```python
from lumiview import App, Window

app = App(name="HelloLumiView")

async def main():
    win = await Window.create(
        title="Hello LumiView!",
        url="https://example.com",
        width=900, height=640,
        devtools=True,
    )
    title = await win.eval_js("document.title")
    print(f"Page title: {title}")

app.run(main)
```

## 核心特性

- **🧵 统一 async/sync** — 所有跨线程/异步操作返回 `Task`。`await`、`.result()` 或 `.on_done()`，同一套 API，自由选择。
- **🌉 JS ↔ Python Bridge** — Python 函数通过 `window.lumiview.invoke()` 暴露给 JS。无需 HTTP 服务器，无需手动序列化。
- **🪟 原生窗口效果** — Acrylic、Mica、Vibrancy `window-vibrancy`。
- **🎨 自定义标题栏** — 声明式 `data-lumiview-drag-region` 拖动区域 + 内置 `lumiview.window.*` JS API（最小化/最大化/关闭）。
- **📁 静态服务 & WSGI & ASGI** — 可直接加载本地文件、代理到 WSGI 应用（Flask、Django 等），或运行 FastAPI/Starlette 应用，无需外部服务器。

可运行代码见 [`examples/`](examples/) 目录。

## 示例

| 示例 | 内容 |
|---|---|
| [`hello_world.py`](examples/hello_world.py) | 最简应用 — 创建窗口、加载 URL（异步） |
| [`hello_world_sync.py`](examples/hello_world_sync.py) | 同上，使用 `.result()` — 纯同步写法 |
| [`bridge_demo.py`](examples/bridge_demo.py) | JS ↔ Python IPC — sync/async 命令、错误处理 |
| [`multi_window.py`](examples/multi_window.py) | 多窗口 + 共享 WebContext |
| [`custom_titlebar.py`](examples/custom_titlebar.py) | 无系统标题栏 + 原生效果 + 拖动区域 |
| [`events.py`](examples/events.py) | App/Window 钩子事件 + JS 事件推送 |
| [`fastapi_demo.py`](examples/fastapi_demo.py) | FastAPI 通过 ``source=ASGI(...)`` 运行 |

## 开发状态

- [x] 窗口管理 (TaoWindow + Window)
- [x] WebView 嵌入 (wryview)
- [x] JS ↔ Python Bridge (IPC + Proxy)
- [x] 钩子事件系统 (AppHookEvent / WindowHookEvent)
- [x] 统一 async/sync `Task` 接口
- [x] 静态文件服务 + WSGI 代理
- [x] ASGI 适配 (FastAPI, Starlette 等)
- [x] 原生窗口效果 (Acrylic / Mica / Vibrancy)
- [x] 自定义标题栏
- [ ] API 稳定化 (may 0.2.x)
- [ ] 完整文档站点

## 参与贡献

这是一个早期项目——**你的反馈至关重要**。

- 🐛 [报告 Bug](https://github.com/xiaosuawa/LumiView/issues)
- 💡 [分享想法](https://github.com/xiaosuawa/LumiView/discussions)
- 🔧 [贡献指南](CONTRIBUTING.md)

在提交 PR 之前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)——API 仍处于不稳定阶段，重大变更需要先讨论。

## License

Copyright (c) 2026 Xiaosu.

Distributed under the terms of the [Mozilla Public License Version 2.0](https://github.com/xiaosuawa/LumiView/blob/main/LICENSE).
