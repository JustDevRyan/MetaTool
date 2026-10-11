<img width="1280" height="340" alt="banner" src="https://github.com/user-attachments/assets/7775e20b-638c-4542-8b25-2c1dcd5d4c7e" />
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="340" viewBox="0 0 1280 340" role="img" aria-label="MetaTool - strip image metadata, inject the metadata you choose, verify the result" xmlns:c2pa="http://c2pa.org/manifest">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#181b25"/>
      <stop offset="1" stop-color="#0c0d11"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#5271ff"/>
      <stop offset="1" stop-color="#a06bff"/>
    </linearGradient>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ff9448"/>
      <stop offset="0.62" stop-color="#8d7cb4"/>
      <stop offset="1" stop-color="#4c68a8"/>
    </linearGradient>
    <clipPath id="photo"><rect x="930" y="40" width="230" height="260" rx="22"/></clipPath>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="14"/>
    </filter>
  </defs>

  <rect width="1280" height="340" rx="26" fill="url(#bg)"/>
  <rect x="0.5" y="0.5" width="1279" height="339" rx="25.5" fill="none" stroke="#2a2d38"/>
  <circle cx="1045" cy="170" r="150" fill="#5271ff" opacity="0.16" filter="url(#glow)"/>

  <!-- title block -->
  <text x="72" y="150" font-family="'Segoe UI','SF Pro Display',-apple-system,'Helvetica Neue',Arial,sans-serif" font-size="92" font-weight="800" fill="#f4f5f8" letter-spacing="-2">MetaTool</text>
  <rect x="76" y="176" width="150" height="6" rx="3" fill="url(#accent)"/>
  <text x="74" y="228" font-family="'Segoe UI','SF Pro Text',-apple-system,'Helvetica Neue',Arial,sans-serif" font-size="27" fill="#aab0bf">Strip the metadata. Write your own.</text>
  <text x="74" y="266" font-family="'Segoe UI','SF Pro Text',-apple-system,'Helvetica Neue',Arial,sans-serif" font-size="27" fill="#8e929b">Then verify the saved file.</text>

  <!-- left chips: what gets removed -->
  <g font-family="'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif" font-size="19" font-weight="600">
    <g transform="translate(610 62)">
      <rect width="230" height="40" rx="20" fill="#2a1d24" stroke="#5b2f3a"/>
      <text x="22" y="26" fill="#ff7a8a">✕  GPS location</text>
    </g>
    <g transform="translate(646 118)">
      <rect width="194" height="40" rx="20" fill="#2a1d24" stroke="#5b2f3a"/>
      <text x="22" y="26" fill="#ff7a8a">✕  XMP · IPTC</text>
    </g>
    <g transform="translate(618 174)">
      <rect width="222" height="40" rx="20" fill="#2a1d24" stroke="#5b2f3a"/>
      <text x="22" y="26" fill="#ff7a8a">✕  ICC · comments</text>
    </g>
    <g transform="translate(662 230)">
      <rect width="178" height="40" rx="20" fill="#2a1d24" stroke="#5b2f3a"/>
      <text x="22" y="26" fill="#ff7a8a">✕  Camera EXIF</text>
    </g>
  </g>

  <!-- arrow -->
  <g stroke="url(#accent)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" fill="none">
    <path d="M858 170 H902"/>
    <path d="M888 154 L904 170 L888 186"/>
  </g>

  <!-- the photo -->
  <g>
    <rect x="930" y="40" width="230" height="260" rx="22" fill="url(#sky)"/>
    <g clip-path="url(#photo)">
      <circle cx="1045" cy="150" r="30" fill="#ffe7a8"/>
      <path d="M930 238 C970 214 1000 214 1040 232 S1120 246 1160 222 V300 H930 Z" fill="#46316e"/>
      <path d="M930 262 C975 242 1015 244 1055 258 S1125 270 1160 252 V300 H930 Z" fill="#271c46"/>
      <path d="M930 282 C980 268 1020 270 1060 280 S1120 288 1160 276 V300 H930 Z" fill="#120d26"/>
    </g>
    <rect x="930" y="40" width="230" height="260" rx="22" fill="none" stroke="#ffffff" stroke-opacity="0.14" stroke-width="2"/>
  </g>

  <!-- right chips: what gets written -->
  <g font-family="'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif" font-size="19" font-weight="600">
    <g transform="translate(1100 72)">
      <rect width="148" height="40" rx="20" fill="#1b2442" stroke="#3a4fa8"/>
      <text x="20" y="26" fill="#9db0ff">✓  Apple</text>
    </g>
    <g transform="translate(1090 128)">
      <rect width="170" height="40" rx="20" fill="#1b2442" stroke="#3a4fa8"/>
      <text x="20" y="26" fill="#9db0ff">✓  iPhone 15</text>
    </g>
    <g transform="translate(1100 184)">
      <rect width="148" height="40" rx="20" fill="#1b2442" stroke="#3a4fa8"/>
      <text x="20" y="26" fill="#9db0ff">✓  iOS 17</text>
    </g>
    <g transform="translate(1076 240)">
      <rect width="172" height="40" rx="20" fill="#1b2442" stroke="#3a4fa8"/>
      <text x="20" y="26" fill="#9db0ff">✓  7/7 checks</text>
    </g>
  </g>
</svg>
