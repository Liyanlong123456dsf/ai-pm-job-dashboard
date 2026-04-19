/**
 * 生成占位图标 SVG + PNG（不依赖外部工具）
 * 运行: node electron/assets/generate-icon.js
 */
const fs = require('fs');
const path = require('path');

const SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#2997ff"/>
      <stop offset="100%" stop-color="#5ac8fa"/>
    </linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="8"/></filter>
  </defs>
  <rect width="512" height="512" rx="96" fill="#0a0a0c"/>
  <rect x="40" y="40" width="432" height="432" rx="80" fill="url(#g)" opacity="0.12"/>
  <text x="256" y="310" font-family="-apple-system,Helvetica,Arial" font-size="220" font-weight="800"
        text-anchor="middle" fill="url(#g)" letter-spacing="-8">AI</text>
  <rect x="128" y="360" width="256" height="4" rx="2" fill="url(#g)" opacity="0.5"/>
  <circle cx="256" cy="400" r="8" fill="url(#g)"/>
</svg>`;

const outDir = __dirname;
fs.writeFileSync(path.join(outDir, 'icon.svg'), SVG);
console.log('✓ icon.svg 已生成');
console.log('');
console.log('如需生成 .ico / .icns / .png，请用以下任一方式：');
console.log('');
console.log('方案1 (最快): https://cloudconvert.com/');
console.log('  上传 icon.svg → 转换为 ico、icns、png');
console.log('');
console.log('方案2 (命令行，需 ImageMagick):');
console.log('  magick icon.svg -resize 256x256 icon.png');
console.log('  magick icon.svg -define icon:auto-resize=256,128,64,48,32,16 icon.ico');
console.log('');
console.log('方案3 (在线): https://icoconverter.com/');
