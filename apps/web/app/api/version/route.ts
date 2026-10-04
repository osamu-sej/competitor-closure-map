import { NextResponse } from 'next/server';
import packageInfo from '../../../../../package.json';

export const dynamic = 'force-dynamic';

export function GET() {
  return NextResponse.json({
    version: packageInfo.version,
    commit: process.env.RENDER_GIT_COMMIT ?? process.env.GITHUB_SHA ?? 'local',
  });
}
