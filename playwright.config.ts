import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests/ui',use:{baseURL:'http://localhost:3000',headless:true,channel:'chrome'},webServer:{command:'npm run dev',url:'http://localhost:3000/api/health',reuseExistingServer:true,timeout:30000}});
