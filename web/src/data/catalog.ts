// 片单数据加载器
// 生产环境读取仓库 data/*.json（由爬取 Agent 通过 PR 提交）；
// 当真实数据为空时，回退到内置示例数据用于预览，并标记 isSample。

import iqiyi from '../../../data/iqiyi.json';
import youku from '../../../data/youku.json';
import mango from '../../../data/mango.json';
import sohu from '../../../data/sohu.json';

export interface CatalogItem {
  id: string;
  title: string;
  poster_url: string | null;
  episodes: number | null;
  update_info: string | null;
  tags: string[];
  vip_required: boolean | null;
  genre: string | null;
  cast: string[] | null;
  director: string | null;
  release_year: number | null;
  description: string | null;
  platform: string;
}

export interface Platform {
  key: string;
  name: string;
  keyword: string;
  color: string; // 平台品牌色
}

export const PLATFORMS: Platform[] = [
  { key: 'iqiyi', name: '爱奇艺', keyword: '爱奇艺影视内容精选', color: '#1cc749' },
  { key: 'youku', name: '优酷', keyword: '优酷视频影视精选', color: '#148aff' },
  { key: 'mango', name: '芒果TV', keyword: '芒果必看精选片单', color: '#ff6a00' },
  { key: 'sohu', name: '搜狐视频', keyword: '抖音片单', color: '#e60012' },
];

const files: Record<string, any> = { iqiyi, youku, mango, sohu };

function loadReal(): CatalogItem[] {
  const items: CatalogItem[] = [];
  for (const key of Object.keys(files)) {
    const file = files[key];
    if (file && Array.isArray(file.items)) {
      for (const it of file.items) {
        items.push({ ...it, platform: it.platform || key });
      }
    }
  }
  return items;
}

// 示例数据：剧名取自抖音官方二创片单指引中真实出现的作品，仅用于预览布局。
const SAMPLE: CatalogItem[] = [
  // 爱奇艺
  s('iqiyi-001', '琅琊榜', 54, ['古装', '权谋'], true, 'iqiyi'),
  s('iqiyi-002', '武林外传', 80, ['古装', '喜剧'], true, 'iqiyi'),
  s('iqiyi-003', '周生如故', 24, ['古装', '爱情'], true, 'iqiyi'),
  s('iqiyi-004', '最好的我们', 24, ['青春', '校园'], true, 'iqiyi'),
  s('iqiyi-005', '中国合伙人', null, ['剧情', '励志'], false, 'iqiyi'),
  s('iqiyi-006', '花样年华', null, ['爱情', '文艺'], false, 'iqiyi'),
  // 优酷
  s('youku-001', '甄嬛传', 76, ['古装', '宫斗'], true, 'youku'),
  s('youku-002', '白夜追凶', 32, ['悬疑', '犯罪'], true, 'youku'),
  s('youku-003', '幸福到万家', 40, ['农村', '励志'], true, 'youku'),
  s('youku-004', '请叫我总监', 36, ['都市', '爱情'], true, 'youku'),
  s('youku-005', '冰雨火', 32, ['缉毒', '悬疑'], true, 'youku'),
  s('youku-006', '点燃我，温暖你', 36, ['都市', '爱情'], true, 'youku'),
  // 芒果TV
  s('mango-001', '乘风2024', null, ['综艺', '舞台'], true, 'mango'),
  s('mango-002', '花儿与少年·好友记', null, ['综艺', '旅行'], true, 'mango'),
  s('mango-003', '群星闪耀时', 24, ['年代', '谍战'], true, 'mango'),
  s('mango-004', '难寻', 24, ['古装', '奇幻'], true, 'mango'),
  s('mango-005', '爸爸当家 第三季', null, ['综艺', '亲子'], true, 'mango'),
  s('mango-006', '灿烂的花园', null, ['综艺', '生活'], true, 'mango'),
  // 搜狐视频
  s('sohu-001', '法医秦明第一季', 20, ['悬疑', '法医'], false, 'sohu'),
  s('sohu-002', '无心法师第一季', 20, ['奇幻', '民国'], false, 'sohu'),
  s('sohu-003', '为你逆光而来', 16, ['都市', '爱情'], false, 'sohu'),
  s('sohu-004', '他在逆光中告白', 16, ['都市', '爱情'], false, 'sohu'),
  s('sohu-005', '夜城赋', 16, ['古装', '悬疑'], false, 'sohu'),
  s('sohu-006', '青梅酸酸你微甜', 12, ['青春', '爱情'], false, 'sohu'),
];

function s(
  id: string,
  title: string,
  episodes: number | null,
  tags: string[],
  vip: boolean,
  platform: string,
): CatalogItem {
  return {
    id,
    title,
    poster_url: null,
    episodes,
    update_info: null,
    tags,
    vip_required: vip,
    genre: tags[0] ?? null,
    cast: null,
    director: null,
    release_year: null,
    description: null,
    platform,
  };
}

const real = loadReal();
export const IS_SAMPLE = real.length === 0;
export const ITEMS: CatalogItem[] = IS_SAMPLE ? SAMPLE : real;

export function platformMeta(key: string): Platform {
  return PLATFORMS.find((p) => p.key === key) ?? {
    key,
    name: key,
    keyword: '',
    color: '#888888',
  };
}
