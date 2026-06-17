# UniLodge Queensland 空房日报

自动抓取 UniLodge Queensland 4 所公寓的空房数据，生成实时房态报告。

## 覆盖公寓

- UniLodge Brisbane City
- UniLodge Park Central
- UniLodge South Bank
- UniLodge Toowong

## 自动更新

通过 GitHub Actions 每天自动更新两次（10:00 / 15:00 AEST）。

## 本地运行

```bash
pip install -r requirements.txt  # 无需额外依赖，仅用标准库
python3 scraper.py
open index.html
```
