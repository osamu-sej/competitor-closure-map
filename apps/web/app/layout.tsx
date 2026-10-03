import type { Metadata } from 'next';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

export const metadata: Metadata = { title: '競合閉店MAP | 神奈川県', description: '店舗マスタの時系列差分から消失候補と確認済み閉店を管理' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="ja"><body>{children}</body></html>; }
