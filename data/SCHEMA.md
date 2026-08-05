# 数据格式规范（SCHEMA）

每个平台一个 JSON 文件，存放于 `data/` 目录：

- `data/iqiyi.json` — 爱奇艺
- `data/youku.json` — 优酷
- `data/mango.json` — 芒果TV
- `data/sohu.json` — 搜狐视频

## 文件结构

```json
{
  "platform": "iqiyi",
  "platform_name": "爱奇艺",
  "source_keyword": "爱奇艺影视内容精选",
  "crawled_at": "2026-07-21",
  "items": [ ... ]
}
```

## 单条影片字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 唯一标识，格式 `{platform}-{序号}`，如 `iqiyi-001` |
| `title` | string | 是 | 片名 |
| `poster_url` | string | 是 | 海报图片 URL（平台 CDN 地址） |
| `episodes` | number \| null | 否 | 集数（电影为 null） |
| `update_info` | string \| null | 否 | 更新状态，如 "更新至24集"、"2024-04-28期" |
| `tags` | string[] | 否 | 标签，如 ["自制", "全网独播", "VIP"] |
| `vip_required` | boolean \| null | 否 | 是否需要 VIP |
| `genre` | string \| null | 否 | 类型：电影/电视剧/综艺/动漫（列表页未展示则留 null） |
| `cast` | string[] \| null | 否 | 主演（列表页未展示则留 null，后续补充） |
| `director` | string \| null | 否 | 导演（后续补充） |
| `release_year` | number \| null | 否 | 上映年份（后续补充） |
| `description` | string \| null | 否 | 简介（后续补充） |
| `douban_rating` | number \| null | 否 | 豆瓣评分（0-10），无豆瓣条目或暂无评分则留 null |
| `heat` | number | 否 | 热度值。片单按"最热"排序爬取，以序号（1 起，即 id 中的编号）× 平台权重计算：爱奇艺 `9×(1000−序号)`、优酷 `10×(800−序号)`、芒果 `8×(600−序号)`，值越大越热 |

**原则：列表页能看到的字段尽量填，看不到的留 `null`，不要编造数据。**

## 示例

```json
{
  "platform": "iqiyi",
  "platform_name": "爱奇艺",
  "source_keyword": "爱奇艺影视内容精选",
  "crawled_at": "2026-07-21",
  "items": [
    {
      "id": "iqiyi-001",
      "title": "琅琊榜",
      "poster_url": "https://pic0.iqiyipic.com/image/xxx.jpg",
      "episodes": 54,
      "update_info": null,
      "tags": [],
      "vip_required": true,
      "genre": "电视剧",
      "cast": null,
      "director": null,
      "release_year": null,
      "description": null,
      "heat": 8991
    }
  ]
}
```

## 提交方式

1. Fork 或 clone 本仓库
2. 将爬取结果写入对应平台的 JSON 文件
3. 提交 PR，标题格式：`data({platform}): 爬取片单数据 {N} 条`
4. 确保 JSON 格式合法（可用 `python -m json.tool data/xxx.json` 校验）
