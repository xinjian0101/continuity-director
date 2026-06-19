# GitHub 与 Comfy Registry 发布

## GitHub

1. 在 GitHub 账户 `xinjian0101` 下新建公开仓库 `continuity-director`。
2. 不要勾选自动创建 README、LICENSE 或 `.gitignore`。
3. 在本项目目录执行：

```bash
git remote add origin https://github.com/xinjian0101/continuity-director.git
git push -u origin main
```

## Comfy Registry

1. 在 Comfy Registry 创建 Publisher。
2. 确认 `pyproject.toml` 中 `PublisherId` 与实际 Publisher ID 一致。
3. 在 GitHub 仓库 Secret 中添加 `REGISTRY_ACCESS_TOKEN`。
4. 手动运行 `Publish to Comfy Registry` 工作流。
