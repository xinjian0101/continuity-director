# Contributing

1. 从 `main` 创建分支。
2. 修改后运行：`python -m compileall -q .`。
3. 运行：`python -m unittest discover -s tests -v`。
4. 新功能必须补充测试和 README。
5. 外部平台适配器必须以当前官方 API 文档为依据，并注明适配版本日期。
