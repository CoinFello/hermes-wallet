/**
 * CoinFello for Hermes — desktop half (pane + statusbar chip).
 *
 * Sign-in is browser-first: one approval on app.coinfello.com, no email code
 * to relay (servers that predate it fall back to the email-code flow). Once
 * signed in, the pane is the minimal portfolio: the automations wallet with
 * copy + QR for funding, the total with its 24h move, and balances grouped
 * per network — the same rules as the CoinFello Portfolio view, applied in
 * the plugin backend (coinfello_portfolio.py). Deeper views open in
 * CoinFello itself.
 *
 * Swap and Earn host CoinFello's own UI (coinfello-web /embed/swap and
 * /embed/earn) in a sandboxed frame, and Full portfolio docks /embed/portfolio
 * in a main-area tab, all through one host; see "embedded views" below. The
 * agent's coinfello_show_card(card="earn_deposit") opens the Earn view.
 *
 * Cards the agent shows (coinfello_show_card) appear at the top of the pane:
 * CoinFello's MCP App cards, each in a sandboxed frame, with the MCP Apps
 * bridge answered here (see "MCP App cards" below).
 *
 * All data flows through the plugin's Python backend at
 * /api/plugins/coinfello — this file never sees the session token.
 */

import {
  Button,
  Codicon,
  CopyButton,
  Input,
  SandboxedFrame,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusDot,
  cn,
  host,
  useQuery,
  useQueryClient,
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'

const ID = 'coinfello'

// -- design system ---------------------------------------------------------------
//
// A hybrid of CoinFello's web UI and the user's Hermes theme. Hermes tokens
// (--ui-text-*, --ui-stroke-*, --ui-widget-surface-background, --ui-green /
// --ui-red, --font-sans / --font-mono) carry every surface, text and state
// colour, so the pane follows whatever theme is active. Actions and highlights
// use the theme's accent (--dt-primary, as Hermes' own primary buttons do);
// Settings > Appearance offers a Hermes theme / CoinFello theme choice
// (CoinFello's yellow). CoinFello
// also contributes the serif portfolio figure
// (Libre Baskerville, as on app.coinfello.com, falling back to system serifs),
// tabular figures, round token icons and rounded cards. The two brand colours
// are the only literals, scoped to the pane like Hermes' own BrandMark tiles.
//
// One injected stylesheet rather than utility classes: a plugin's classes are
// not in the app's compiled Tailwind, so utilities it alone uses never exist.

// CoinFello's wordmark (coinfello-web public/CoinFello-logo.svg). The
// lettering is currentColor so it reads on light and dark themes; the coin
// mark keeps its own colours. Ids are namespaced to stay unique in the page.
const LOGO_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" role="img" aria-label="CoinFello" fill="none" viewBox="0 0 122 25"><path fill="currentColor" fill-rule="evenodd" d="M36.499 3.696c-.222.015-.535.047-.696.071s-.439.076-.616.115c-.178.039-.508.13-.733.202a8 8 0 0 0-.856.344 8 8 0 0 0-.769.422 8 8 0 0 0-.578.42c-.14.115-.398.358-.573.54a8 8 0 0 0-.537.625 9 9 0 0 0-.407.607c-.103.17-.277.496-.387.725s-.273.637-.362.909c-.09.271-.205.699-.256.95-.052.252-.12.647-.152.879s-.067.825-.079 1.32c-.013.566-.004 1.102.023 1.446.024.301.084.778.132 1.06s.144.719.214.972c.07.252.188.615.262.805s.218.507.318.704.311.55.469.787c.157.236.417.58.578.763s.436.455.61.604c.175.149.46.367.635.484.175.118.516.311.757.43.242.118.579.265.75.328a9 9 0 0 0 1.575.39c.328.052.636.066 1.391.065.718-.001 1.09-.018 1.428-.065.252-.035.647-.106.879-.158.232-.051.602-.152.824-.223.221-.07.584-.207.805-.303s.547-.255.722-.353c.176-.098.473-.285.66-.416.186-.13.529-.427.76-.659.233-.231.533-.577.668-.769a7.7 7.7 0 0 0 .834-1.629c.063-.181.154-.477.202-.657.061-.226.076-.336.049-.352a47 47 0 0 0-1.363-.437c-.728-.227-1.337-.414-1.353-.417-.016-.002-.091.177-.168.399-.076.221-.184.51-.24.64a6 6 0 0 1-.23.476c-.073.131-.214.362-.315.513-.1.15-.308.4-.46.552a4 4 0 0 1-.498.425c-.12.081-.319.197-.44.258-.12.061-.36.16-.532.222-.173.06-.47.143-.66.184a9 9 0 0 1-.803.119 6.732 6.732 0 0 1-1.718-.058 7 7 0 0 1-.604-.153 5 5 0 0 1-.607-.25 5 5 0 0 1-.567-.338c-.141-.1-.374-.298-.517-.44a4.4 4.4 0 0 1-.467-.567 5 5 0 0 1-.33-.583 7 7 0 0 1-.235-.62 9 9 0 0 1-.184-.692c-.04-.19-.095-.504-.122-.695-.032-.23-.049-.728-.048-1.465 0-.887.014-1.203.066-1.537.036-.232.107-.594.158-.806.051-.211.148-.525.214-.698s.166-.403.22-.512c.056-.11.181-.316.28-.458.097-.142.322-.4.498-.572a5 5 0 0 1 .637-.519c.174-.113.425-.255.558-.314.133-.06.369-.149.525-.198s.455-.118.664-.153c.311-.052.517-.06 1.135-.043.55.016.855.042 1.12.096.2.041.496.119.659.172.162.054.426.163.587.244s.387.21.501.287c.115.078.307.233.428.344.12.112.309.322.419.467s.277.398.371.562c.094.163.26.516.368.783.109.267.218.565.243.663s.063.179.083.179.652-.193 1.404-.428l1.367-.428-.024-.112c-.013-.062-.081-.302-.15-.533a9 9 0 0 0-.273-.764 8 8 0 0 0-.332-.674 8 8 0 0 0-.455-.687 7 7 0 0 0-.64-.71 7 7 0 0 0-.816-.651 10 10 0 0 0-.993-.563 10 10 0 0 0-.933-.395c-.212-.072-.59-.18-.842-.24s-.632-.135-.845-.166c-.213-.03-.658-.072-.989-.092s-.667-.035-.747-.032-.328.017-.55.032m22.168 1.701v1.556h3.185V3.842h-3.185zM76.79 12.19v8.347h3.039v-6.992h7.651v-2.71h-7.652V6.551h8.897V3.842H76.789zm24.749 0v8.347h3.075V3.842h-3.075zm4.283 0v8.347h3.076V3.842h-3.076zM69.41 8.399a6 6 0 0 0-.6.149 6 6 0 0 0-.575.22 6 6 0 0 0-.59.33 5 5 0 0 0-.645.533 6 6 0 0 1-.339.325c-.007 0-.013-.33-.013-.733v-.732H63.61v12.045h3.037l.01-3.707.011-3.706.082-.293c.045-.161.15-.433.234-.604.118-.24.216-.375.43-.589.153-.152.37-.328.48-.39a3.3 3.3 0 0 1 .476-.206c.15-.05.435-.11.631-.131.256-.028.459-.028.714 0 .197.022.487.082.645.135.158.052.388.16.512.24.123.08.315.24.426.355.111.116.258.304.326.417s.164.317.213.453c.05.135.117.362.149.503.05.222.06.732.071 3.89l.014 3.633h3.002l-.012-3.981c-.012-3.935-.013-3.986-.093-4.39a8 8 0 0 0-.192-.747 6 6 0 0 0-.255-.627 6 6 0 0 0-.333-.562 5 5 0 0 0-.483-.57 5 5 0 0 0-.553-.478 5 5 0 0 0-.572-.34 5 5 0 0 0-.604-.252 7 7 0 0 0-.55-.155q-.255-.057-.988-.072c-.525-.01-.815 0-1.027.038m-18.194.095a7 7 0 0 0-.824.106c-.21.043-.58.143-.818.223a7 7 0 0 0-.794.325c-.199.099-.465.25-.592.335a8 8 0 0 0-.524.4c-.161.135-.41.384-.553.553-.144.168-.351.447-.462.618s-.26.426-.33.567a6.2 6.2 0 0 0-.435 1.222c-.04.168-.096.481-.124.696a10 10 0 0 0-.053 1.019c0 .356.023.813.055 1.052.03.233.08.531.11.663.032.133.1.376.151.54.052.165.159.439.238.609s.252.475.386.677c.166.252.39.515.704.829.288.288.58.54.78.671.177.117.482.291.678.388s.529.237.739.31c.21.072.58.174.824.226.36.076.58.097 1.182.113.472.012.87.004 1.099-.024.196-.024.505-.078.687-.12.181-.041.494-.132.695-.202a8 8 0 0 0 .723-.303c.197-.097.495-.268.664-.38.17-.113.417-.303.55-.424s.338-.326.456-.456c.117-.129.313-.38.434-.558a7 7 0 0 0 .393-.666c.094-.189.227-.51.295-.714s.157-.536.198-.738c.04-.2.093-.596.116-.878a9 9 0 0 0 .017-.952 11 11 0 0 0-.077-.802c-.029-.2-.096-.53-.15-.732a7 7 0 0 0-.238-.716 6 6 0 0 0-.323-.653 8 8 0 0 0-.381-.569 5.934 5.934 0 0 0-1.272-1.198 7 7 0 0 0-.562-.336 7.715 7.715 0 0 0-1.434-.534 7 7 0 0 0-.782-.148 12 12 0 0 0-.677-.053 9 9 0 0 0-.769.014m42.818 0a7 7 0 0 0-.806.106 9 9 0 0 0-.822.224c-.24.08-.608.235-.817.343a7 7 0 0 0-.678.411c-.165.117-.456.37-.648.562a7 7 0 0 0-.595.696c-.135.19-.335.527-.445.749a6 6 0 0 0-.31.75c-.06.192-.143.524-.184.739s-.092.639-.113.943a8 8 0 0 0 0 1.11c.021.307.078.758.128 1.003s.141.599.204.787.19.49.28.672c.09.18.244.444.34.585.095.142.283.385.416.54.134.156.37.392.526.526.156.133.407.324.558.424s.44.263.643.361c.203.099.54.237.75.307s.547.162.749.206c.286.061.54.083 1.16.098.494.012.928.003 1.153-.023.198-.024.516-.075.707-.113.191-.04.504-.123.696-.186s.498-.187.682-.274.489-.263.677-.39c.205-.137.514-.4.767-.651.27-.27.506-.546.653-.767.126-.19.303-.493.393-.672s.158-.341.151-.361c-.006-.02-.522-.249-1.146-.51-.623-.26-1.154-.473-1.179-.473-.024 0-.072.054-.106.12a5 5 0 0 1-.209.338 3.989 3.989 0 0 1-.849.878c-.12.086-.31.202-.42.258s-.316.14-.455.187a5 5 0 0 1-.565.145 5 5 0 0 1-.771.057c-.344 0-.535-.02-.754-.076a3.7 3.7 0 0 1-.585-.22 3.4 3.4 0 0 1-.502-.312 2.5 2.5 0 0 1-.393-.427 3 3 0 0 1-.297-.555 6 6 0 0 1-.183-.572 2.4 2.4 0 0 1-.07-.397l-.001-.12h8.777l.024-.118c.014-.066.034-.325.046-.577.012-.254.003-.67-.021-.934a10 10 0 0 0-.117-.842 5.78 5.78 0 0 0-.452-1.37 9 9 0 0 0-.282-.507 7 7 0 0 0-.381-.543 6 6 0 0 0-.547-.592 6 6 0 0 0-.615-.495 7 7 0 0 0-.63-.365 9 9 0 0 0-.686-.297 8 8 0 0 0-.72-.222 7 7 0 0 0-.705-.126c-.188-.02-.49-.044-.671-.052a9 9 0 0 0-.75.014m21.344 0a8 8 0 0 0-.836.104 8 8 0 0 0-.802.206c-.213.07-.544.202-.736.293a7 7 0 0 0-.71.405c-.197.131-.508.38-.69.554a6 6 0 0 0-.58.647c-.137.183-.335.48-.438.662a6 6 0 0 0-.33.695 7 7 0 0 0-.219.678c-.042.171-.104.484-.138.696-.041.26-.061.621-.062 1.116-.001.52.017.854.062 1.154.036.231.089.52.119.64.03.121.097.352.149.513s.165.441.252.622.237.448.334.593.296.403.441.574.392.421.549.555.409.326.56.426.455.27.677.378c.221.107.585.253.807.324s.576.167.787.213c.34.073.487.083 1.317.084.833.002.978-.007 1.348-.082a9 9 0 0 0 .805-.212c.215-.07.563-.21.774-.311s.549-.293.751-.427c.235-.156.513-.39.772-.649.267-.267.493-.538.667-.799.145-.217.33-.533.41-.702.081-.17.198-.458.259-.643.062-.184.144-.477.182-.652s.088-.505.112-.734c.027-.257.036-.686.023-1.117a7 7 0 0 0-.097-1.114 8 8 0 0 0-.19-.768 7 7 0 0 0-.236-.623 6 6 0 0 0-.259-.494 8 8 0 0 0-.33-.49 7 7 0 0 0-.441-.527 5.7 5.7 0 0 0-1.019-.83 9 9 0 0 0-.64-.333 8 8 0 0 0-.75-.311 9 9 0 0 0-.604-.167 7 7 0 0 0-.659-.11 12 12 0 0 0-.659-.05 9 9 0 0 0-.732.012M58.74 14.568v5.967h3.039V8.601H58.74zM52.626 11c.13.034.34.108.464.164.125.056.302.154.394.217s.25.197.35.297.246.277.324.392.183.292.233.393c.05.1.135.314.187.476.052.16.12.424.149.585.03.161.065.49.079.732a6 6 0 0 1-.13 1.6c-.038.175-.113.43-.168.567a5 5 0 0 1-.242.498 3.2 3.2 0 0 1-.363.483c-.121.13-.314.297-.428.373a3 3 0 0 1-.52.256c-.17.064-.45.137-.619.161a4.4 4.4 0 0 1-.75.024 3 3 0 0 1-1.34-.345 2.8 2.8 0 0 1-.533-.428 2.2 2.2 0 0 1-.451-.6 5 5 0 0 1-.247-.567 6 6 0 0 1-.162-.68 5.6 5.6 0 0 1-.071-1.007 8 8 0 0 1 .054-.939c.029-.19.087-.47.13-.62.041-.15.132-.394.201-.543.07-.149.199-.374.289-.5s.252-.31.361-.409c.11-.098.29-.234.402-.3a3 3 0 0 1 .91-.335c.108-.019.436-.029.728-.021.344.008.615.035.769.076m42.67-.004c.121.033.342.117.492.187s.374.202.499.291c.125.09.32.264.431.388.112.123.269.35.349.504a4.4 4.4 0 0 1 .335.922c0 .022-1.061.035-2.805.035h-2.805l.025-.137c.015-.076.08-.28.145-.455s.175-.414.244-.531.257-.346.418-.507c.227-.228.367-.333.622-.463.182-.093.429-.195.55-.227.12-.032.252-.065.292-.075s.28-.012.531-.005c.267.008.55.038.678.073m21.178-.05c.13.02.367.081.528.134.16.053.408.173.551.267s.343.26.444.368c.102.11.236.273.298.363.061.09.158.255.214.366s.139.312.185.447.113.382.15.55c.054.245.067.462.066 1.145-.001.781-.008.872-.098 1.25a5 5 0 0 1-.229.714 4 4 0 0 1-.333.589c-.11.155-.3.366-.423.468a3 3 0 0 1-.473.311c-.137.07-.371.16-.518.203a3.3 3.3 0 0 1-.744.096 3.5 3.5 0 0 1-.819-.04 3.5 3.5 0 0 1-.615-.173 3.2 3.2 0 0 1-.534-.301 2.6 2.6 0 0 1-.437-.405 3.6 3.6 0 0 1-.318-.494 4.4 4.4 0 0 1-.24-.584 7 7 0 0 1-.157-.64c-.043-.236-.061-.536-.06-1.012 0-.483.018-.778.063-1.025.035-.192.118-.51.185-.706s.202-.49.3-.653c.111-.183.284-.396.454-.558.161-.155.38-.318.532-.397.142-.075.381-.168.531-.209s.314-.08.364-.088c.051-.009.273-.018.495-.02s.509.012.638.033" clip-rule="evenodd"/><rect width="23.997" height="24.079" fill="#fe0" rx="6.411"/><mask id="cf-logo-a" width="16" height="17" x="3.862" y="3.589" fill="#000" maskUnits="userSpaceOnUse"><path fill="#fff" d="M3.862 3.589h16v17h-16z"/><path fill-rule="evenodd" d="M10.058 5.594a1 1 0 0 0-.151.03 1.098 1.098 0 0 0-.363.186 1 1 0 0 0-.135.133c-.032.038-.076.1-.098.137a1 1 0 0 0-.07.143c-.016.041-.039.12-.05.173a.8.8 0 0 0-.012.227l.012.175c.003.026.273.981.6 2.124l.74 2.582c.08.278.144.524.144.547s-.01.058-.022.079a.2.2 0 0 1-.05.054.2.2 0 0 1-.064.024.14.14 0 0 1-.089-.015.2.2 0 0 1-.07-.05c-.01-.015-.106-.344-.215-.731l-.793-2.826a14 14 0 0 0-.225-.756 1 1 0 0 1-.06-.1 1 1 0 0 0-.09-.146 1 1 0 0 0-.107-.121 1 1 0 0 0-.127-.103 1 1 0 0 0-.142-.08 2 2 0 0 0-.164-.06.8.8 0 0 0-.248-.025 1 1 0 0 0-.239.02 1.208 1.208 0 0 0-.363.174c-.039.031-.098.085-.13.12a1 1 0 0 0-.116.157c-.031.05-.074.143-.095.206a.7.7 0 0 0-.043.266 1 1 0 0 0 .014.244c.01.05.108.359.216.685l.837 2.522c.352 1.06.64 1.945.64 1.966s-.01.055-.023.076a.2.2 0 0 1-.057.055.2.2 0 0 1-.077.018.2.2 0 0 1-.075-.017.2.2 0 0 1-.056-.05c-.013-.018-.14-.388-.285-.823l-.654-1.972a48 48 0 0 0-.406-1.198 1 1 0 0 1-.065-.105 1 1 0 0 0-.123-.158.7.7 0 0 0-.17-.12 1 1 0 0 0-.166-.066.9.9 0 0 0-.35 0 .704.704 0 0 0-.327.183 1 1 0 0 0-.126.148 1 1 0 0 0-.07.153 1 1 0 0 0-.036.18.6.6 0 0 0 .01.174 66.793 66.793 0 0 0 .747 2.955 59 59 0 0 0 .367 1.237 27.106 27.106 0 0 0 .386 1.149 12.805 12.805 0 0 0 .352.884 4.985 4.985 0 0 0 .278.55c.041.069.119.183.173.253s.165.202.245.292a6 6 0 0 0 .595.575 6.621 6.621 0 0 0 .814.576 7 7 0 0 0 .63.311 5.17 5.17 0 0 0 .774.245 6 6 0 0 0 .546.09c.073.009.264.016.424.016s.351-.007.425-.015c.073-.008.2-.024.28-.037s.228-.042.33-.065a5 5 0 0 0 .395-.11c.15-.05.274-.1.432-.178a6 6 0 0 0 .378-.202c.086-.052.213-.133.281-.18s.189-.135.267-.196c.079-.06.214-.173.3-.25a7.568 7.568 0 0 0 .645-.663 8.724 8.724 0 0 0 .48-.64c.052-.077.13-.2.175-.273s.119-.202.164-.285a7 7 0 0 0 .248-.516c.025-.06.119-.35.208-.646l.24-.793.373-1.24.389-1.285c.05-.166.097-.342.105-.39a1 1 0 0 0 .006-.193 1.4 1.4 0 0 0-.03-.198 1 1 0 0 0-.077-.2.8.8 0 0 0-.137-.196 1.4 1.4 0 0 0-.143-.133 1.3 1.3 0 0 0-.434-.192 1 1 0 0 0-.35 0c-.042.01-.11.03-.151.048a1 1 0 0 0-.154.082 1.2 1.2 0 0 0-.273.262c-.02.029-.057.092-.082.14-.026.047-.189.36-.363.697l-.546 1.048a1.7 1.7 0 0 1-.165.276.333.333 0 0 1-.205.115.47.47 0 0 1-.26-.057.3.3 0 0 1-.11-.089.7.7 0 0 1-.074-.159c-.02-.057-.12-.408-.221-.78L13.479 7.77c-.14-.514-.21-.753-.24-.815a.831.831 0 0 0-.198-.278 1 1 0 0 0-.12-.088.774.774 0 0 0-1.148.479c-.01.046-.018.136-.019.213l-.001.134.2.82.245 1.013.204.837.339 1.4c.058.236.06.256.046.292a.2.2 0 0 1-.052.069.2.2 0 0 1-.07.037.2.2 0 0 1-.074-.005.2.2 0 0 1-.07-.045c-.027-.028-.048-.104-.17-.602l-.488-1.995-.396-1.616a44 44 0 0 0-.33-1.303.6.6 0 0 1-.048-.104A1 1 0 0 0 11 6.04a1 1 0 0 0-.137-.166 1 1 0 0 0-.165-.131c-.049-.03-.13-.07-.18-.089a1 1 0 0 0-.156-.045 1.04 1.04 0 0 0-.303-.014" clip-rule="evenodd"/></mask><path fill="#fff" fill-rule="evenodd" d="M10.058 5.594a1 1 0 0 0-.151.03 1.098 1.098 0 0 0-.363.186 1 1 0 0 0-.135.133c-.032.038-.076.1-.098.137a1 1 0 0 0-.07.143c-.016.041-.039.12-.05.173a.8.8 0 0 0-.012.227l.012.175c.003.026.273.981.6 2.124l.74 2.582c.08.278.144.524.144.547s-.01.058-.022.079a.2.2 0 0 1-.05.054.2.2 0 0 1-.064.024.14.14 0 0 1-.089-.015.2.2 0 0 1-.07-.05c-.01-.015-.106-.344-.215-.731l-.793-2.826a14 14 0 0 0-.225-.756 1 1 0 0 1-.06-.1 1 1 0 0 0-.09-.146 1 1 0 0 0-.107-.121 1 1 0 0 0-.127-.103 1 1 0 0 0-.142-.08 2 2 0 0 0-.164-.06.8.8 0 0 0-.248-.025 1 1 0 0 0-.239.02 1.208 1.208 0 0 0-.363.174c-.039.031-.098.085-.13.12a1 1 0 0 0-.116.157c-.031.05-.074.143-.095.206a.7.7 0 0 0-.043.266 1 1 0 0 0 .014.244c.01.05.108.359.216.685l.837 2.522c.352 1.06.64 1.945.64 1.966s-.01.055-.023.076a.2.2 0 0 1-.057.055.2.2 0 0 1-.077.018.2.2 0 0 1-.075-.017.2.2 0 0 1-.056-.05c-.013-.018-.14-.388-.285-.823l-.654-1.972a48 48 0 0 0-.406-1.198 1 1 0 0 1-.065-.105 1 1 0 0 0-.123-.158.7.7 0 0 0-.17-.12 1 1 0 0 0-.166-.066.9.9 0 0 0-.35 0 .704.704 0 0 0-.327.183 1 1 0 0 0-.126.148 1 1 0 0 0-.07.153 1 1 0 0 0-.036.18.6.6 0 0 0 .01.174 66.793 66.793 0 0 0 .747 2.955 59 59 0 0 0 .367 1.237 27.106 27.106 0 0 0 .386 1.149 12.805 12.805 0 0 0 .352.884 4.985 4.985 0 0 0 .278.55c.041.069.119.183.173.253s.165.202.245.292a6 6 0 0 0 .595.575 6.621 6.621 0 0 0 .814.576 7 7 0 0 0 .63.311 5.17 5.17 0 0 0 .774.245 6 6 0 0 0 .546.09c.073.009.264.016.424.016s.351-.007.425-.015c.073-.008.2-.024.28-.037s.228-.042.33-.065a5 5 0 0 0 .395-.11c.15-.05.274-.1.432-.178a6 6 0 0 0 .378-.202c.086-.052.213-.133.281-.18s.189-.135.267-.196c.079-.06.214-.173.3-.25a7.568 7.568 0 0 0 .645-.663 8.724 8.724 0 0 0 .48-.64c.052-.077.13-.2.175-.273s.119-.202.164-.285a7 7 0 0 0 .248-.516c.025-.06.119-.35.208-.646l.24-.793.373-1.24.389-1.285c.05-.166.097-.342.105-.39a1 1 0 0 0 .006-.193 1.4 1.4 0 0 0-.03-.198 1 1 0 0 0-.077-.2.8.8 0 0 0-.137-.196 1.4 1.4 0 0 0-.143-.133 1.3 1.3 0 0 0-.434-.192 1 1 0 0 0-.35 0c-.042.01-.11.03-.151.048a1 1 0 0 0-.154.082 1.2 1.2 0 0 0-.273.262c-.02.029-.057.092-.082.14-.026.047-.189.36-.363.697l-.546 1.048a1.7 1.7 0 0 1-.165.276.333.333 0 0 1-.205.115.47.47 0 0 1-.26-.057.3.3 0 0 1-.11-.089.7.7 0 0 1-.074-.159c-.02-.057-.12-.408-.221-.78L13.479 7.77c-.14-.514-.21-.753-.24-.815a.831.831 0 0 0-.198-.278 1 1 0 0 0-.12-.088.774.774 0 0 0-1.148.479c-.01.046-.018.136-.019.213l-.001.134.2.82.245 1.013.204.837.339 1.4c.058.236.06.256.046.292a.2.2 0 0 1-.052.069.2.2 0 0 1-.07.037.2.2 0 0 1-.074-.005.2.2 0 0 1-.07-.045c-.027-.028-.048-.104-.17-.602l-.488-1.995-.396-1.616a44 44 0 0 0-.33-1.303.6.6 0 0 1-.048-.104A1 1 0 0 0 11 6.04a1 1 0 0 0-.137-.166 1 1 0 0 0-.165-.131c-.049-.03-.13-.07-.18-.089a1 1 0 0 0-.156-.045 1.04 1.04 0 0 0-.303-.014" clip-rule="evenodd"/><path stroke="#000" stroke-width="2.343" d="M10.058 5.594a1 1 0 0 0-.151.03 1.098 1.098 0 0 0-.363.186 1 1 0 0 0-.135.133c-.032.038-.076.1-.098.137a1 1 0 0 0-.07.143c-.016.041-.039.12-.05.173a.8.8 0 0 0-.012.227l.012.175c.003.026.273.981.6 2.124l.74 2.582c.08.278.144.524.144.547s-.01.058-.022.079a.2.2 0 0 1-.05.054.2.2 0 0 1-.064.024.14.14 0 0 1-.089-.015.2.2 0 0 1-.07-.05c-.01-.015-.106-.344-.215-.731l-.793-2.826a14 14 0 0 0-.225-.756 1 1 0 0 1-.06-.1 1 1 0 0 0-.09-.146 1 1 0 0 0-.107-.121 1 1 0 0 0-.127-.103 1 1 0 0 0-.142-.08 2 2 0 0 0-.164-.06.8.8 0 0 0-.248-.025 1 1 0 0 0-.239.02 1.208 1.208 0 0 0-.363.174c-.039.031-.098.085-.13.12a1 1 0 0 0-.116.157c-.031.05-.074.143-.095.206a.7.7 0 0 0-.043.266 1 1 0 0 0 .014.244c.01.05.108.359.216.685l.837 2.522c.352 1.06.64 1.945.64 1.966s-.01.055-.023.076a.2.2 0 0 1-.057.055.2.2 0 0 1-.077.018.2.2 0 0 1-.075-.017.2.2 0 0 1-.056-.05c-.013-.018-.14-.388-.285-.823l-.654-1.972a48 48 0 0 0-.406-1.198 1 1 0 0 1-.065-.105 1 1 0 0 0-.123-.158.7.7 0 0 0-.17-.12 1 1 0 0 0-.166-.066.9.9 0 0 0-.35 0 .704.704 0 0 0-.327.183 1 1 0 0 0-.126.148 1 1 0 0 0-.07.153 1 1 0 0 0-.036.18.6.6 0 0 0 .01.174 66.793 66.793 0 0 0 .747 2.955 59 59 0 0 0 .367 1.237 27.106 27.106 0 0 0 .386 1.149 12.805 12.805 0 0 0 .352.884 4.985 4.985 0 0 0 .278.55c.041.069.119.183.173.253s.165.202.245.292a6 6 0 0 0 .595.575 6.621 6.621 0 0 0 .814.576 7 7 0 0 0 .63.311 5.17 5.17 0 0 0 .774.245 6 6 0 0 0 .546.09c.073.009.264.016.424.016s.351-.007.425-.015c.073-.008.2-.024.28-.037s.228-.042.33-.065a5 5 0 0 0 .395-.11c.15-.05.274-.1.432-.178a6 6 0 0 0 .378-.202c.086-.052.213-.133.281-.18s.189-.135.267-.196c.079-.06.214-.173.3-.25a7.568 7.568 0 0 0 .645-.663 8.724 8.724 0 0 0 .48-.64c.052-.077.13-.2.175-.273s.119-.202.164-.285a7 7 0 0 0 .248-.516c.025-.06.119-.35.208-.646l.24-.793.373-1.24.389-1.285c.05-.166.097-.342.105-.39a1 1 0 0 0 .006-.193 1.4 1.4 0 0 0-.03-.198 1 1 0 0 0-.077-.2.8.8 0 0 0-.137-.196 1.4 1.4 0 0 0-.143-.133 1.3 1.3 0 0 0-.434-.192 1 1 0 0 0-.35 0c-.042.01-.11.03-.151.048a1 1 0 0 0-.154.082 1.2 1.2 0 0 0-.273.262c-.02.029-.057.092-.082.14-.026.047-.189.36-.363.697l-.546 1.048a1.7 1.7 0 0 1-.165.276.333.333 0 0 1-.205.115.47.47 0 0 1-.26-.057.3.3 0 0 1-.11-.089.7.7 0 0 1-.074-.159c-.02-.057-.12-.408-.221-.78L13.479 7.77c-.14-.514-.21-.753-.24-.815a.831.831 0 0 0-.198-.278 1 1 0 0 0-.12-.088.774.774 0 0 0-1.148.479c-.01.046-.018.136-.019.213l-.001.134.2.82.245 1.013.204.837.339 1.4c.058.236.06.256.046.292a.2.2 0 0 1-.052.069.2.2 0 0 1-.07.037.2.2 0 0 1-.074-.005.2.2 0 0 1-.07-.045c-.027-.028-.048-.104-.17-.602l-.488-1.995-.396-1.616a44 44 0 0 0-.33-1.303.6.6 0 0 1-.048-.104A1 1 0 0 0 11 6.04a1 1 0 0 0-.137-.166 1 1 0 0 0-.165-.131c-.049-.03-.13-.07-.18-.089a1 1 0 0 0-.156-.045 1.04 1.04 0 0 0-.303-.014Z" clip-rule="evenodd" mask="url(#cf-logo-a)"/><mask id="cf-logo-b" fill="#fff"><path fill-rule="evenodd" d="M10.058 5.594a1 1 0 0 0-.151.03 1.098 1.098 0 0 0-.363.186 1 1 0 0 0-.135.133c-.032.038-.076.1-.098.137a1 1 0 0 0-.07.143c-.016.041-.039.12-.05.173a.8.8 0 0 0-.012.227l.012.175c.003.026.273.981.6 2.124l.74 2.582c.08.278.144.524.144.547s-.01.058-.022.079a.2.2 0 0 1-.05.054.2.2 0 0 1-.064.024.14.14 0 0 1-.089-.015.2.2 0 0 1-.07-.05c-.01-.015-.106-.344-.215-.731l-.793-2.826a14 14 0 0 0-.225-.756 1 1 0 0 1-.06-.1 1 1 0 0 0-.09-.146 1 1 0 0 0-.107-.121 1 1 0 0 0-.127-.103 1 1 0 0 0-.142-.08 2 2 0 0 0-.164-.06.8.8 0 0 0-.248-.025 1 1 0 0 0-.239.02 1.208 1.208 0 0 0-.363.174c-.039.031-.098.085-.13.12a1 1 0 0 0-.116.157c-.031.05-.074.143-.095.206a.7.7 0 0 0-.043.266 1 1 0 0 0 .014.244c.01.05.108.359.216.685l.837 2.522c.352 1.06.64 1.945.64 1.966s-.01.055-.023.076a.2.2 0 0 1-.057.055.2.2 0 0 1-.077.018.2.2 0 0 1-.075-.017.2.2 0 0 1-.056-.05c-.013-.018-.14-.388-.285-.823l-.654-1.972a48 48 0 0 0-.406-1.198 1 1 0 0 1-.065-.105 1 1 0 0 0-.123-.158.7.7 0 0 0-.17-.12 1 1 0 0 0-.166-.066.9.9 0 0 0-.35 0 .704.704 0 0 0-.327.183 1 1 0 0 0-.126.148 1 1 0 0 0-.07.153 1 1 0 0 0-.036.18.6.6 0 0 0 .01.174 66.793 66.793 0 0 0 .747 2.955 59 59 0 0 0 .367 1.237 27.106 27.106 0 0 0 .386 1.149 12.805 12.805 0 0 0 .352.884 4.985 4.985 0 0 0 .278.55c.041.069.119.183.173.253s.165.202.245.292a6 6 0 0 0 .595.575 6.621 6.621 0 0 0 .814.576 7 7 0 0 0 .63.311 5.17 5.17 0 0 0 .774.245 6 6 0 0 0 .546.09c.073.009.264.016.424.016s.351-.007.425-.015c.073-.008.2-.024.28-.037s.228-.042.33-.065a5 5 0 0 0 .395-.11c.15-.05.274-.1.432-.178a6 6 0 0 0 .378-.202c.086-.052.213-.133.281-.18s.189-.135.267-.196c.079-.06.214-.173.3-.25a7.568 7.568 0 0 0 .645-.663 8.724 8.724 0 0 0 .48-.64c.052-.077.13-.2.175-.273s.119-.202.164-.285a7 7 0 0 0 .248-.516c.025-.06.119-.35.208-.646l.24-.793.373-1.24.389-1.285c.05-.166.097-.342.105-.39a1 1 0 0 0 .006-.193 1.4 1.4 0 0 0-.03-.198 1 1 0 0 0-.077-.2.8.8 0 0 0-.137-.196 1.4 1.4 0 0 0-.143-.133 1.3 1.3 0 0 0-.434-.192 1 1 0 0 0-.35 0c-.042.01-.11.03-.151.048a1 1 0 0 0-.154.082 1.2 1.2 0 0 0-.273.262c-.02.029-.057.092-.082.14-.026.047-.189.36-.363.697l-.546 1.048a1.7 1.7 0 0 1-.165.276.333.333 0 0 1-.205.115.47.47 0 0 1-.26-.057.3.3 0 0 1-.11-.089.7.7 0 0 1-.074-.159c-.02-.057-.12-.408-.221-.78L13.479 7.77c-.14-.514-.21-.753-.24-.815a.831.831 0 0 0-.198-.278 1 1 0 0 0-.12-.088.774.774 0 0 0-1.148.479c-.01.046-.018.136-.019.213l-.001.134.2.82.245 1.013.204.837.339 1.4c.058.236.06.256.046.292a.2.2 0 0 1-.052.069.2.2 0 0 1-.07.037.2.2 0 0 1-.074-.005.2.2 0 0 1-.07-.045c-.027-.028-.048-.104-.17-.602l-.488-1.995-.396-1.616a44 44 0 0 0-.33-1.303.6.6 0 0 1-.048-.104A1 1 0 0 0 11 6.04a1 1 0 0 0-.137-.166 1 1 0 0 0-.165-.131c-.049-.03-.13-.07-.18-.089a1 1 0 0 0-.156-.045 1.04 1.04 0 0 0-.303-.014" clip-rule="evenodd"/></mask><path fill="#fff" fill-rule="evenodd" stroke="#000" stroke-width=".124" d="M10.058 5.594a1 1 0 0 0-.151.03 1.098 1.098 0 0 0-.363.186 1 1 0 0 0-.135.133c-.032.038-.076.1-.098.137a1 1 0 0 0-.07.143c-.016.041-.039.12-.05.173a.8.8 0 0 0-.012.227l.012.175c.003.026.273.981.6 2.124l.74 2.582c.08.278.144.524.144.547s-.01.058-.022.079a.2.2 0 0 1-.05.054.2.2 0 0 1-.064.024.14.14 0 0 1-.089-.015.2.2 0 0 1-.07-.05c-.01-.015-.106-.344-.215-.731l-.793-2.826a14 14 0 0 0-.225-.756 1 1 0 0 1-.06-.1 1 1 0 0 0-.09-.146 1 1 0 0 0-.107-.121 1 1 0 0 0-.127-.103 1 1 0 0 0-.142-.08 2 2 0 0 0-.164-.06.8.8 0 0 0-.248-.025 1 1 0 0 0-.239.02 1.208 1.208 0 0 0-.363.174c-.039.031-.098.085-.13.12a1 1 0 0 0-.116.157c-.031.05-.074.143-.095.206a.7.7 0 0 0-.043.266 1 1 0 0 0 .014.244c.01.05.108.359.216.685l.837 2.522c.352 1.06.64 1.945.64 1.966s-.01.055-.023.076a.2.2 0 0 1-.057.055.2.2 0 0 1-.077.018.2.2 0 0 1-.075-.017.2.2 0 0 1-.056-.05c-.013-.018-.14-.388-.285-.823l-.654-1.972a48 48 0 0 0-.406-1.198 1 1 0 0 1-.065-.105 1 1 0 0 0-.123-.158.7.7 0 0 0-.17-.12 1 1 0 0 0-.166-.066.9.9 0 0 0-.35 0 .704.704 0 0 0-.327.183 1 1 0 0 0-.126.148 1 1 0 0 0-.07.153 1 1 0 0 0-.036.18.6.6 0 0 0 .01.174 66.793 66.793 0 0 0 .747 2.955 59 59 0 0 0 .367 1.237 27.106 27.106 0 0 0 .386 1.149 12.805 12.805 0 0 0 .352.884 4.985 4.985 0 0 0 .278.55c.041.069.119.183.173.253s.165.202.245.292a6 6 0 0 0 .595.575 6.621 6.621 0 0 0 .814.576 7 7 0 0 0 .63.311 5.17 5.17 0 0 0 .774.245 6 6 0 0 0 .546.09c.073.009.264.016.424.016s.351-.007.425-.015c.073-.008.2-.024.28-.037s.228-.042.33-.065a5 5 0 0 0 .395-.11c.15-.05.274-.1.432-.178a6 6 0 0 0 .378-.202c.086-.052.213-.133.281-.18s.189-.135.267-.196c.079-.06.214-.173.3-.25a7.568 7.568 0 0 0 .645-.663 8.724 8.724 0 0 0 .48-.64c.052-.077.13-.2.175-.273s.119-.202.164-.285a7 7 0 0 0 .248-.516c.025-.06.119-.35.208-.646l.24-.793.373-1.24.389-1.285c.05-.166.097-.342.105-.39a1 1 0 0 0 .006-.193 1.4 1.4 0 0 0-.03-.198 1 1 0 0 0-.077-.2.8.8 0 0 0-.137-.196 1.4 1.4 0 0 0-.143-.133 1.3 1.3 0 0 0-.434-.192 1 1 0 0 0-.35 0c-.042.01-.11.03-.151.048a1 1 0 0 0-.154.082 1.2 1.2 0 0 0-.273.262c-.02.029-.057.092-.082.14-.026.047-.189.36-.363.697l-.546 1.048a1.7 1.7 0 0 1-.165.276.333.333 0 0 1-.205.115.47.47 0 0 1-.26-.057.3.3 0 0 1-.11-.089.7.7 0 0 1-.074-.159c-.02-.057-.12-.408-.221-.78L13.479 7.77c-.14-.514-.21-.753-.24-.815a.831.831 0 0 0-.198-.278 1 1 0 0 0-.12-.088.774.774 0 0 0-1.148.479c-.01.046-.018.136-.019.213l-.001.134.2.82.245 1.013.204.837.339 1.4c.058.236.06.256.046.292a.2.2 0 0 1-.052.069.2.2 0 0 1-.07.037.2.2 0 0 1-.074-.005.2.2 0 0 1-.07-.045c-.027-.028-.048-.104-.17-.602l-.488-1.995-.396-1.616a44 44 0 0 0-.33-1.303.6.6 0 0 1-.048-.104A1 1 0 0 0 11 6.04a1 1 0 0 0-.137-.166 1 1 0 0 0-.165-.131c-.049-.03-.13-.07-.18-.089a1 1 0 0 0-.156-.045 1.04 1.04 0 0 0-.303-.014Z" clip-rule="evenodd" mask="url(#cf-logo-b)"/><path stroke="#000" stroke-linecap="round" stroke-width=".433" d="M14.75 13.783c-.15.261-.393.973-.156 1.727"/></svg>`

const STYLE_ID = 'coinfello-plugin-styles'
const STYLES = `
.cf {
  /* Accent for actions and highlights: the Hermes theme's primary (what its
     own primary buttons use) unless the user opts into CoinFello colors. */
  --cf-accent: var(--dt-primary);
  --cf-accent-ink: var(--dt-primary-foreground, #fff);
  --cf-brand: #ffee00;
  --cf-brand-ink: #1c1800;
  --cf-warn: #e5b400;
  --cf-violet: #8556e5;
  --cf-radius: 12px;
  --cf-serif: 'Libre Baskerville', 'Noto Serif', 'DejaVu Serif', Georgia, serif;
  display: flex; flex-direction: column; gap: 14px;
  height: 100%; overflow: auto; padding: 12px 12px 16px;
  font-family: var(--font-sans); font-size: 13px; color: var(--ui-text-primary);
}
/* The pane scrolls; its blocks never shrink to fit. As flex items they would:
   the hero's overflow:hidden drops its min-height to 0, so a long Activity
   list squashed the wallet card to a sliver instead of scrolling the pane. */
.cf > * { flex-shrink: 0; }
.cf button { font: inherit; }
.cf.is-brand { --cf-accent: var(--cf-brand); --cf-accent-ink: var(--cf-brand-ink); }
/* SDK primary buttons (bg-primary) follow the same choice. */
.cf.is-brand button.bg-primary { background-color: var(--cf-accent); color: var(--cf-accent-ink); }
.cf.is-brand button.bg-primary:hover { background-color: var(--cf-accent); filter: brightness(1.05); }
.cf-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 28px; }
.cf-logo { display: block; width: 104px; height: 21px; color: var(--ui-text-primary); }
.cf-header-end { display: flex; align-items: center; gap: 4px; }
.cf-status { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ui-text-tertiary); margin-right: 2px; }
.cf-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ui-text-quaternary); flex: none; }
.cf-dot.is-on { background: var(--ui-green); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ui-green) 22%, transparent); }
.cf-dot.is-warn { background: var(--cf-warn); box-shadow: 0 0 0 3px color-mix(in srgb, var(--cf-warn) 25%, transparent); }
.cf-icon-btn { display: inline-grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: 7px;
  background: transparent; color: var(--ui-text-secondary); cursor: pointer; }
.cf-icon-btn:hover { background: var(--chrome-action-hover); color: var(--ui-text-primary); }
.cf-icon-btn:focus-visible, .cf-action:focus-visible, .cf-chip:focus-visible, .cf-link:focus-visible, .cf-notice:focus-visible, .cf-token:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--cf-accent) 70%, var(--ui-text-primary)); outline-offset: 2px; }

.cf-card { background: var(--ui-widget-surface-background); border: 1px solid var(--ui-stroke-tertiary);
  border-radius: var(--cf-radius); padding: 14px; }
.cf-hero { position: relative; overflow: hidden;
  background-image: radial-gradient(120% 90% at 100% 0%, color-mix(in srgb, var(--cf-accent) 9%, transparent), transparent 58%); }
.cf-eyebrow { white-space: nowrap; font-size: 11px; font-weight: 500; letter-spacing: .04em; text-transform: uppercase; color: var(--ui-text-tertiary); }
.cf-hero-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.cf-chip { white-space: nowrap; flex: none; display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 3px 9px; border: 0; border-radius: 999px;
  background: var(--ui-bg-quaternary); color: var(--ui-text-secondary); font-family: var(--font-mono); font-size: 11.5px; cursor: pointer; }
.cf-chip:hover { background: var(--chrome-action-hover); color: var(--ui-text-primary); }
.cf-balance { margin: 10px 0 2px; font-family: var(--cf-serif); font-size: 31px; line-height: 1.12; letter-spacing: -.01em;
  font-variant-numeric: tabular-nums; color: var(--ui-text-primary); }
.cf-change { font-size: 12px; font-variant-numeric: tabular-nums; }
.cf-up { color: var(--ui-green); }
.cf-down { color: var(--ui-red); }
.cf-muted { color: var(--ui-text-tertiary); }
.cf-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 16px; }
.cf-action { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 4px 0; border: 0; border-radius: 10px;
  background: transparent; color: var(--ui-text-secondary); font-size: 11.5px; cursor: pointer; }
.cf-action-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%;
  background: var(--ui-bg-quaternary); color: var(--ui-text-primary); transition: transform .12s ease, filter .12s ease; }
.cf-action.is-primary .cf-action-icon { background: var(--cf-accent); color: var(--cf-accent-ink); }
.cf-action:not(:disabled):hover { color: var(--ui-text-primary); }
.cf-action:not(:disabled):hover .cf-action-icon { transform: translateY(-1px); filter: brightness(1.06); }
.cf-action:disabled { cursor: not-allowed; opacity: .42; }
.cf-actions.is-four { grid-template-columns: repeat(4, 1fr); }

.cf-notice { display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 11px; border-radius: 10px; text-align: left; cursor: pointer;
  border: 1px solid color-mix(in srgb, var(--cf-accent) 38%, var(--ui-stroke-tertiary));
  background: color-mix(in srgb, var(--cf-accent) 9%, transparent); color: var(--ui-text-primary); font-size: 12px; }
.cf-notice:hover { background: color-mix(in srgb, var(--cf-accent) 15%, transparent); }
.cf-notice-text { flex: 1; min-width: 0; }
.cf-notice-text b { font-weight: 600; }
.cf-notice.is-static { cursor: default; }
.cf-notice.is-static:hover { background: color-mix(in srgb, var(--cf-accent) 9%, transparent); }

/* Embedded views (swap, Earn) and the agent's MCP App cards. */
.cf-embed-frame { display: block; width: 100%; border: 0; border-radius: var(--cf-radius); }
.cf-embed-outcome { display: flex; flex-direction: column; gap: 6px; padding: 0 2px; }
.cf-embed-outcome-title { font-size: 12.5px; font-weight: 600; }
.cf-embed-outcome-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.cf-card-box { position: relative; width: 100%; overflow: hidden; border-radius: var(--cf-radius); }
.cf-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 2px; }
.cf-card-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; font-weight: 600; }
.cf-confirm { border-color: color-mix(in srgb, var(--cf-accent) 45%, var(--ui-stroke-tertiary)); }
.cf-confirm-title { font-size: 13px; font-weight: 600; }

.cf-section { display: flex; flex-direction: column; gap: 6px; }
.cf-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 0 2px; }
.cf-section-title { font-size: 12.5px; font-weight: 600; color: var(--ui-text-primary); }
.cf-section-aside { font-size: 11px; color: var(--ui-text-tertiary); font-variant-numeric: tabular-nums; }
.cf-net + .cf-net { margin-top: 6px; }
.cf-net-head { display: flex; justify-content: space-between; padding: 4px 4px 2px; font-size: 11px; color: var(--ui-text-tertiary);
  font-variant-numeric: tabular-nums; }
.cf-net-name { display: inline-flex; align-items: center; gap: 6px; min-width: 0; font-weight: 600; color: var(--ui-text-primary); }
.cf-net-name > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-net-logo { width: 16px; height: 16px; flex: none; border-radius: 50%; object-fit: cover; overflow: hidden; }
.cf-net-logo.is-letter { display: grid; place-items: center; background: var(--ui-bg-quaternary); color: var(--ui-text-secondary);
  font-size: 9px; font-weight: 600; }
.cf-token { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 7px 4px; border-radius: 9px; }
.cf-token:hover { background: var(--chrome-action-hover); }
.cf-token-icon { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; background: var(--ui-bg-quaternary); }
.cf-token-fallback { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: var(--ui-bg-quaternary);
  color: var(--ui-text-secondary); font-size: 10px; font-weight: 600; }
.cf-token-name { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-token-sub, .cf-token-change { font-size: 11.5px; color: var(--ui-text-tertiary); font-variant-numeric: tabular-nums;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-token-value { text-align: right; font-size: 13px; font-variant-numeric: tabular-nums; }
.cf-token-change { text-align: right; }

.cf-tabs { display: inline-flex; gap: 14px; }
.cf-tab { position: relative; padding: 0 0 4px; border: 0; background: transparent; cursor: pointer;
  font-size: 12.5px; font-weight: 600; color: var(--ui-text-tertiary); }
.cf-tab:hover { color: var(--ui-text-secondary); }
.cf-tab.is-active { color: var(--ui-text-primary); }
.cf-tab.is-active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; border-radius: 2px; background: var(--cf-accent); }
.cf-tab:focus-visible { outline: 2px solid color-mix(in srgb, var(--cf-accent) 70%, var(--ui-text-primary)); outline-offset: 2px; border-radius: 3px; }

.cf-act-day + .cf-act-day { margin-top: 6px; }
.cf-act-day-label { font-weight: 600; color: var(--ui-text-primary); }
.cf-act-row { display: grid; grid-template-columns: 26px minmax(0, 1fr) auto; align-items: start; gap: 9px; width: 100%;
  padding: 7px 4px; border: 0; border-radius: 9px; background: transparent; color: inherit; text-align: left; }
.cf-act-row.is-link { cursor: pointer; }
.cf-act-row.is-link:hover { background: var(--chrome-action-hover); }
.cf-act-row.is-link:focus-visible { outline: 2px solid color-mix(in srgb, var(--cf-accent) 70%, var(--ui-text-primary)); outline-offset: -2px; }
.cf-act-marker { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%;
  background: var(--ui-bg-quaternary); color: var(--ui-text-secondary); }
.cf-act-marker.is-accent { background: color-mix(in srgb, var(--cf-accent) 22%, var(--ui-bg-quaternary)); color: var(--ui-text-primary); }
.cf-act-marker.is-good { background: color-mix(in srgb, var(--ui-green) 18%, transparent); color: var(--ui-green); }
.cf-act-marker.is-bad { background: color-mix(in srgb, var(--ui-red) 16%, transparent); color: var(--ui-red); }
.cf-act-pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--ui-text-tertiary); animation: cf-pulse 1.4s ease-in-out infinite; }
.cf-act-marker.is-live .cf-act-pulse { background: var(--ui-green); }
.cf-act-main { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.cf-act-sentence { font-size: 12.5px; line-height: 1.4; color: var(--ui-text-primary); overflow-wrap: anywhere;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.cf-act-meta { font-size: 11px; color: var(--ui-text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-act-result { padding-top: 1px; font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
.cf-err-text { color: var(--ui-red); }
.cf-act-empty { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 22px 14px; text-align: center; color: var(--ui-text-tertiary); }
.cf-act-empty-title { font-size: 13px; font-weight: 600; color: var(--ui-text-primary); }

.cf-links { display: flex; flex-wrap: wrap; gap: 6px; }
.cf-link { display: inline-flex; align-items: center; gap: 5px; padding: 5px 11px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--ui-stroke-tertiary); background: transparent; color: var(--ui-text-secondary); font-size: 12px; }
.cf-link:hover { background: var(--chrome-action-hover); color: var(--ui-text-primary); }
.cf-link.is-soon { cursor: default; color: var(--ui-text-tertiary); border-style: dashed; }
.cf-link.is-soon:hover { background: transparent; color: var(--ui-text-tertiary); }
.cf-soon { font-size: 10.5px; color: var(--ui-text-quaternary); }

.cf-subhead { display: flex; align-items: center; gap: 6px; min-height: 28px; }
.cf-subhead-title { font-size: 14px; font-weight: 600; }
.cf-rows > * + * { border-top: 1px solid var(--ui-stroke-tertiary); }
.cf-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 0; }
.cf-rows > .cf-row:first-child { padding-top: 0; }
.cf-rows > .cf-row:last-child { padding-bottom: 0; }
.cf-row-label { font-size: 12px; color: var(--ui-text-tertiary); }
.cf-row-value { min-width: 0; font-size: 12.5px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-account { display: flex; align-items: center; gap: 10px; min-width: 0; }
.cf-avatar { display: grid; place-items: center; width: 36px; height: 36px; flex: none; border-radius: 50%;
  background: color-mix(in srgb, var(--cf-violet) 85%, black); color: #fff; font-weight: 600; font-size: 14px; }
.cf-account-name { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cf-hint { font-size: 11.5px; line-height: 1.45; color: var(--ui-text-tertiary); }
.cf-danger-btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 0; border: 0; background: transparent;
  color: var(--ui-red); font-size: 12.5px; cursor: pointer; }
.cf-danger-btn:hover { text-decoration: underline; }

.cf-qr { width: 196px; margin: 4px auto 0; padding: 12px; border-radius: var(--cf-radius); background: #fff; }
.cf-qr img { display: block; width: 172px; height: 172px; }
.cf-mono { font-family: var(--font-mono); font-size: 11.5px; word-break: break-all; }
.cf-center { text-align: center; }

.cf-chip.is-static { cursor: default; }
.cf-chip.is-static:hover { background: var(--ui-bg-quaternary); color: var(--ui-text-secondary); }
.cf-action[aria-pressed="true"] .cf-action-icon { background: color-mix(in srgb, var(--cf-accent) 26%, var(--ui-bg-quaternary)); }
.cf-allow-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.cf-allow-state { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 500; color: var(--ui-text-secondary); }
.cf-allow-figure { margin-top: 8px; font-family: var(--cf-serif); font-size: 24px; line-height: 1.15; font-variant-numeric: tabular-nums; }
.cf-allow-figure small { font-family: var(--font-sans); font-size: 12px; color: var(--ui-text-tertiary); margin-left: 3px; }
.cf-meter { height: 6px; margin: 10px 0 6px; border-radius: 999px; background: var(--ui-bg-quaternary); overflow: hidden; }
.cf-meter > span { display: block; height: 100%; border-radius: inherit; background: var(--cf-accent); transition: width .3s ease; }
.cf-allow-left .cf-allow-figure small { margin-left: 6px; }
.cf-allow-left > .cf-hint:first-of-type { margin-top: 2px; }
.cf-meter-legend { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; font-size: 11.5px;
  color: var(--ui-text-tertiary); font-variant-numeric: tabular-nums; margin-bottom: 6px; }
.cf-meter-legend > span { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.cf-meter-legend b { font-weight: 600; color: var(--ui-text-primary); }
.cf-swatch { width: 8px; height: 8px; border-radius: 2px; flex: none; }
.cf-swatch.is-left { background: var(--cf-accent); }
.cf-swatch.is-used { background: var(--ui-bg-quaternary); box-shadow: inset 0 0 0 1px var(--ui-stroke-secondary, var(--ui-stroke-tertiary)); }
.cf-meter.is-empty { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--cf-warn) 60%, transparent); }

.cf-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.cf-radios { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 0; border: 0; min-width: 0; }
.cf-radio { display: flex; align-items: center; gap: 10px; padding: 9px 11px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--ui-stroke-tertiary); }
.cf-radio:hover { background: var(--chrome-action-hover); }
.cf-radio.is-checked { border-color: color-mix(in srgb, var(--cf-accent) 70%, var(--ui-stroke-tertiary));
  background: color-mix(in srgb, var(--cf-accent) 8%, transparent); }
.cf-radio input { flex: none; width: 15px; height: 15px; margin: 0; accent-color: var(--cf-accent); cursor: pointer; }
.cf-radio input:focus-visible { outline: 2px solid color-mix(in srgb, var(--cf-accent) 70%, var(--ui-text-primary)); outline-offset: 2px; }
.cf-radio-text { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.cf-radio-label { font-size: 12.5px; font-weight: 500; color: var(--ui-text-primary); }
.cf-radio-swatch { width: 16px; height: 16px; flex: none; border-radius: 50%; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ui-text-primary) 15%, transparent); }
.cf-stack { display: flex; flex-direction: column; gap: 10px; }
.cf-ok { font-size: 12px; color: var(--ui-green); }
.cf-err { font-size: 12px; color: var(--ui-red); }

@keyframes cf-pulse { 0%, 100% { opacity: .55 } 50% { opacity: 1 } }
.cf-skeleton { border-radius: 8px; background: var(--ui-bg-quaternary); animation: cf-pulse 1.4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .cf-skeleton, .cf-act-pulse { animation: none; }
  .cf-action-icon, .cf-meter > span { transition: none; }
}
`

function installStyles(ctx) {
  document.getElementById(STYLE_ID)?.remove() // a hot reload replaces, never stacks
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = STYLES
  document.head.appendChild(style)
  ctx.onDispose(() => style.remove())
}

function Logo() {
  return jsx('span', { className: 'cf-logo', dangerouslySetInnerHTML: { __html: LOGO_SVG } })
}

const muted = 'text-(--ui-text-tertiary)'
const row = 'flex items-center justify-between gap-2'
const up = 'cf-up'
const down = 'cf-down'

const shortAddr = (address) =>
  address && address.length > 14 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address || ''

const shortDate = (iso) => {
  const date = iso ? new Date(iso) : null
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : ''
}

function errorOf(result, fallback) {
  return (result && result.error) || fallback
}

// -- small pieces --------------------------------------------------------------

function TokenLogo({ token }) {
  // TokenIcon.tsx's chain: provider logo -> MetaMask icon API -> generic.
  const sources = [token.logo_url, token.fallback_logo_url].filter(Boolean)
  const [index, setIndex] = useState(0)
  if (index >= sources.length) {
    return jsx('div', { className: 'cf-token-fallback', children: (token.symbol || '?').slice(0, 3) })
  }
  return jsx('img', { src: sources[index], alt: '', className: 'cf-token-icon', onError: () => setIndex(index + 1) })
}

// Network icons, as coinfello-web's NetworkToken: the chain's native-token icon
// from MetaMask's CDN, local overrides for chains it lacks, then the app's
// generic blockchain icon, then the network's first letter.
const NATIVE_TOKEN_ADDRESS = '0x0000000000000000000000000000000000000000'
const CHAIN_ICON_OVERRIDES = {
  130: '/Icons/chains/unichain.svg',
  4663: '/Icons/chains/robinhood.png',
  57073: '/Icons/chains/ink.svg',
}

function originOf(url) {
  try {
    return new URL(url).origin
  } catch {
    return 'https://app.coinfello.com'
  }
}

function ChainLogo({ chainId, name, appOrigin }) {
  const override = CHAIN_ICON_OVERRIDES[Number(chainId)]
  const sources = [
    override ? appOrigin + override : `https://static.cx.metamask.io/api/v1/tokenIcons/${chainId}/${NATIVE_TOKEN_ADDRESS}.png`,
    `${appOrigin}/Icons/Blockchain-icon.svg`,
  ]
  const [index, setIndex] = useState(0)
  if (index >= sources.length) {
    return jsx('span', { className: 'cf-net-logo is-letter', 'aria-hidden': true, children: (name || '?').slice(0, 1) })
  }
  return jsx('img', { src: sources[index], alt: '', className: 'cf-net-logo', loading: 'lazy', onError: () => setIndex(index + 1) })
}

function ExternalButton({ ctx, url, label, icon }) {
  return jsx(Button, {
    variant: 'outline',
    size: 'sm',
    className: 'flex-1',
    onClick: () => ctx.os.openExternal(url),
    children: jsxs(Fragment, {
      children: [jsx(Codicon, { name: icon || 'link-external', size: 12 }), label],
    }),
  })
}

/** A view not available in Hermes yet: shown, not clickable, with why. */
function SoonPill({ label, note }) {
  return jsxs('span', {
    className: 'cf-link is-soon',
    'aria-disabled': true,
    title: note,
    children: [label, jsx('span', { className: 'cf-soon', children: note })],
  })
}

/** Opens a view in a Hermes tab (the counterpart of LinkPill's browser link). */
function TabPill({ onClick, label }) {
  return jsxs('button', {
    type: 'button',
    className: 'cf-link',
    onClick,
    children: [label, jsx(Codicon, { name: 'arrow-right', size: 11 })],
  })
}

function LinkPill({ ctx, url, label }) {
  if (!url) return null
  return jsxs('button', {
    type: 'button',
    className: 'cf-link',
    onClick: () => ctx.os.openExternal(url),
    children: [label, jsx(Codicon, { name: 'link-external', size: 11 })],
  })
}

function ActionButton({ icon, label, primary, active, disabled, title, onClick }) {
  return jsxs('button', {
    type: 'button',
    className: cn('cf-action', primary && 'is-primary'),
    disabled,
    title,
    'aria-pressed': active === undefined ? undefined : active,
    onClick,
    children: [jsx('span', { className: 'cf-action-icon', children: jsx(Codicon, { name: icon, size: 16 }) }), label],
  })
}

const useWallet = (ctx) =>
  useQuery({ queryKey: ['coinfello', 'wallet'], queryFn: () => ctx.rest('/wallet'), staleTime: 5 * 60 * 1000 })
const usePortfolio = (ctx) =>
  useQuery({ queryKey: ['coinfello', 'portfolio'], queryFn: () => ctx.rest('/portfolio'), refetchInterval: 60 * 1000 })

// -- signed-in home: hero (wallet + total + actions), allowance notice, assets --

function blockedReason(data, verb) {
  if (!data) return undefined
  return data.can_trade === false
    ? 'Read-only: set a trading allowance in Settings'
    : `${verb} from Hermes needs a CoinFello update`
}

function Hero({ ctx, onSend, onSwap, onEarn }) {
  const [showQr, setShowQr] = useState(false)
  const wallet = useWallet(ctx)
  const portfolio = usePortfolio(ctx)
  const w = wallet.data && wallet.data.ok !== false ? wallet.data : null
  const p = portfolio.data && portfolio.data.ok !== false ? portfolio.data : null
  // Read-only sessions may browse Earn: the server decides on deposits.
  const earn = !!(p && p.earn_supported)

  let figure
  if (p) {
    figure = jsxs(Fragment, {
      children: [
        jsx('div', { className: 'cf-balance', children: p.total_text }),
        jsxs('div', {
          className: cn('cf-change', p.change_positive ? 'cf-up' : 'cf-down'),
          children: [p.change_24h_text, jsx('span', { className: 'cf-muted', children: '  past 24h' })],
        }),
      ],
    })
  } else if (portfolio.isLoading) {
    figure = jsxs(Fragment, {
      children: [
        jsx('div', { className: 'cf-skeleton', style: { width: 148, height: 32, margin: '12px 0 6px' } }),
        jsx('div', { className: 'cf-skeleton', style: { width: 84, height: 12 } }),
      ],
    })
  } else {
    figure = jsx('div', { className: 'cf-hint', style: { marginTop: 12 }, children: errorOf(portfolio.data, 'Could not load balances.') })
  }

  return jsxs('section', {
    className: 'cf-card cf-hero',
    children: [
      jsxs('div', {
        className: 'cf-hero-top',
        children: [
          jsx('span', { className: 'cf-eyebrow', children: 'Automations wallet' }),
          w
            ? jsxs('div', {
                className: 'flex items-center gap-0.5',
                children: [
                  jsx('span', { className: 'cf-chip is-static', title: w.address, children: shortAddr(w.address) }),
                  jsx(CopyButton, { text: w.address, appearance: 'icon', label: 'Copy address' }),
                ],
              })
            : wallet.isLoading
              ? jsx('span', { className: 'cf-skeleton', style: { width: 96, height: 20 } })
              : null,
        ],
      }),
      figure,
      jsxs('div', {
        className: cn('cf-actions', earn && 'is-four'),
        children: [
          jsx(ActionButton, {
            icon: 'arrow-up',
            label: 'Send',
            primary: true,
            disabled: !(p && p.can_send),
            title: p && p.can_send ? undefined : blockedReason(p, 'Sending'),
            onClick: () => onSend(p),
          }),
          jsx(ActionButton, {
            icon: 'arrow-swap',
            label: 'Swap',
            disabled: !(p && p.can_swap),
            title: p && p.can_swap ? undefined : blockedReason(p, 'Swapping'),
            onClick: onSwap,
          }),
          earn ? jsx(ActionButton, { icon: 'graph-line', label: 'Earn', onClick: onEarn }) : null,
          jsx(ActionButton, {
            icon: 'arrow-down',
            label: 'Receive',
            active: showQr,
            disabled: !w,
            onClick: () => setShowQr(!showQr),
          }),
        ],
      }),
      p && p.earn_supported === false
        ? jsx('div', {
            className: 'cf-hint',
            style: { marginTop: 10 },
            children: 'Earn opens here once CoinFello updates. Until then, ask the agent for yields to see them as a card.',
          })
        : null,
      showQr && w
        ? jsxs('div', {
            className: 'cf-stack',
            style: { marginTop: 14 },
            children: [
              w.qr_svg
                ? jsx('div', {
                    // Dark-on-light regardless of theme: scanners need the contrast.
                    className: 'cf-qr',
                    children: jsx('img', { src: w.qr_svg, alt: 'Wallet address QR code' }),
                  })
                : jsx('div', { className: 'cf-hint cf-center', children: 'QR unavailable (run hermes pm repair to install segno).' }),
              jsx('div', { className: 'cf-mono cf-center', children: w.address }),
              jsx('div', {
                className: 'cf-hint cf-center',
                children: 'Send tokens on a network CoinFello supports. This address is the same on every EVM network.',
              }),
            ],
          })
        : null,
    ],
  })
}

/** Home's one line about the allowance; the controls live in Settings. */
function AllowanceNotice({ status, message, onOpen }) {
  let icon
  let text
  if (status.pending_limit_change_url) {
    icon = 'clock'
    text = [jsx('b', { children: 'Allowance change pending.' }, 'b'), ' Approve it on CoinFello in your browser.']
  } else if (status.access && status.access !== 'unknown' && status.access !== 'trade') {
    icon = 'lock'
    text = [jsx('b', { children: 'Read-only.' }, 'b'), ' Set a trading allowance to send or swap.']
  } else if (message) {
    icon = 'check'
    text = message
  } else {
    return null
  }
  return jsxs('button', {
    type: 'button',
    className: 'cf-notice',
    onClick: onOpen,
    children: [
      jsx(Codicon, { name: icon, size: 14 }),
      jsx('span', { className: 'cf-notice-text', children: text }),
      jsx(Codicon, { name: 'chevron-right', size: 14 }),
    ],
  })
}

const HOME_TABS = [
  { id: 'assets', label: 'Assets' },
  { id: 'activity', label: 'Activity' },
]

/** Assets | Activity, as a tablist in the section-title style. */
function HomeTabs({ tab, setTab, aside }) {
  const onKeyDown = (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const next = HOME_TABS[(HOME_TABS.findIndex((t) => t.id === tab) + 1) % HOME_TABS.length]
    setTab(next.id)
    event.currentTarget.parentElement?.querySelector(`[data-tab="${next.id}"]`)?.focus()
  }
  return jsxs('div', {
    className: 'cf-section-head',
    children: [
      jsx('div', {
        className: 'cf-tabs',
        role: 'tablist',
        'aria-label': 'Wallet',
        children: HOME_TABS.map((t) =>
          jsx(
            'button',
            {
              type: 'button',
              role: 'tab',
              id: `cf-tab-${t.id}`,
              'data-tab': t.id,
              'aria-selected': tab === t.id,
              'aria-controls': `cf-panel-${t.id}`,
              tabIndex: tab === t.id ? 0 : -1,
              className: cn('cf-tab', tab === t.id && 'is-active'),
              onClick: () => setTab(t.id),
              onKeyDown,
              children: t.label,
            },
            t.id,
          ),
        ),
      }),
      aside ? jsx('span', { className: 'cf-section-aside', children: aside }) : null,
    ],
  })
}

function Assets({ ctx, tab, setTab }) {
  const portfolio = usePortfolio(ctx)
  const data = portfolio.data
  if (tab === 'activity') {
    return jsxs('section', {
      className: 'cf-section',
      children: [
        jsx(HomeTabs, { tab, setTab }),
        jsx('div', { id: 'cf-panel-activity', role: 'tabpanel', 'aria-labelledby': 'cf-tab-activity', className: 'cf-section', children: jsx(Activity, { ctx }) }),
      ],
    })
  }
  if (!data || data.ok === false) return null
  const networks = data.networks || []
  const appOrigin = originOf(data.portfolio_url)
  const tabs = canOpenTabs()
  const portfolioInApp = tabs && data.can_view_portfolio === true
  const strategiesInApp = tabs && data.can_view_strategies === true
  // No browser fallback: the web app reconnects a browser-extension wallet and
  // can sign in as a different account. Until the server offers a view, its
  // pill says it is coming. A server that offers it to a desktop too old for
  // main-area tabs says to update Hermes instead.
  const soon = (offered) => (offered && !tabs ? 'Update Hermes to open this' : 'Coming to Hermes soon')
  return jsxs('section', {
    className: 'cf-section',
    id: 'cf-panel-assets',
    role: 'tabpanel',
    'aria-labelledby': 'cf-tab-assets',
    children: [
      jsx(HomeTabs, { tab, setTab, aside: networks.length ? `${networks.length} network${networks.length === 1 ? '' : 's'}` : null }),
      networks.length === 0
        ? jsx('div', { className: 'cf-card cf-hint', children: 'No tokens yet. Use Receive to fund this wallet.' })
        : jsx('div', {
            className: 'cf-card',
            style: { padding: 6 },
            children: networks.map((network) =>
              jsxs(
                'div',
                {
                  className: 'cf-net',
                  children: [
                    jsxs('div', {
                      className: 'cf-net-head',
                      children: [
                        jsxs('span', {
                          className: 'cf-net-name',
                          children: [
                            jsx(ChainLogo, { chainId: network.chain_id, name: network.chain_name, appOrigin }),
                            jsx('span', { children: network.chain_name }),
                          ],
                        }),
                        jsx('span', { children: network.subtotal_text }),
                      ],
                    }),
                    ...network.tokens.map((token, index) =>
                      jsxs(
                        'div',
                        {
                          className: 'cf-token',
                          children: [
                            jsx(TokenLogo, { token }),
                            jsxs('div', {
                              className: 'min-w-0',
                              children: [
                                jsx('div', { className: 'cf-token-name', children: token.symbol }),
                                jsx('div', { className: 'cf-token-sub', children: token.balance_text }),
                              ],
                            }),
                            jsxs('div', {
                              children: [
                                jsx('div', { className: 'cf-token-value', children: token.value_text }),
                                token.change_text
                                  ? jsx('div', {
                                      className: cn('cf-token-change', token.change_positive ? 'cf-up' : 'cf-down'),
                                      children: token.change_text,
                                    })
                                  : null,
                              ],
                            }),
                          ],
                        },
                        `${network.chain_id}-${token.symbol}-${index}`,
                      ),
                    ),
                  ],
                },
                String(network.chain_id),
              ),
            ),
          }),
      data.hidden_count > 0 || data.truncated
        ? jsx('div', {
            className: 'cf-hint',
            style: { padding: '0 2px' },
            children: [
              data.hidden_count > 0 ? `${data.hidden_count} unpriced token${data.hidden_count === 1 ? '' : 's'} hidden.` : '',
              data.truncated ? ' Smallest balances not shown.' : '',
            ].join(' ').trim(),
          })
        : null,
      jsxs('div', {
        className: 'cf-links',
        children: [
          portfolioInApp
            ? jsx(TabPill, { onClick: () => openEmbedTab(ctx, appOrigin, 'portfolio'), label: 'Full portfolio' })
            : jsx(SoonPill, { label: 'Full portfolio', note: soon(data.can_view_portfolio === true) }),
          strategiesInApp
            ? jsx(TabPill, { onClick: () => openEmbedTab(ctx, appOrigin, 'strategies'), label: 'Strategies' })
            : jsx(SoonPill, { label: 'Strategies', note: soon(data.can_view_strategies === true) }),
        ],
      }),
    ],
  })
}

// -- activity: the wallet's history, worded like the CoinFello activity feed ----
//
// Rows arrive already worded (coinfello_activity.py ports the web app's
// sentence/result rules). Pages follow the server's cursor; Hyperliquid fills
// come only with the first page (the server reads them by time window), so
// while older transactions remain unloaded, only fills inside the loaded span
// are shown — otherwise a 6-day-old fill would sit above unloaded rows.

// Custom 16px line icons where the codicon set has no fitting glyph, drawn in
// its style (1.25 stroke, round caps) and coloured by currentColor.
const ACTIVITY_ICONS = {
  // Two opposed arrows: one token traded for another.
  swap: '<path d="M2.5 5.5h10.5M10.5 3l2.5 2.5-2.5 2.5M13.5 10.5H3M5.5 8 3 10.5 5.5 13"/>',
  // A key: a contract was given permission to spend a token.
  allowance: '<circle cx="4.75" cy="8" r="3"/><path d="M7.75 8h6.75M12 8v2.5M14.5 8v2"/>',
  // An arch bridge: funds moved from one network to another.
  bridge: '<path d="M1 10h14M2 10Q8 2 14 10M5 7v3M8 6v4M11 7v3M3 10v3.5M13 10v3.5"/>',
}

function ActivityIcon({ name, size = 14 }) {
  return jsx('svg', {
    xmlns: 'http://www.w3.org/2000/svg',
    width: size,
    height: size,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.25,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
    dangerouslySetInnerHTML: { __html: ACTIVITY_ICONS[name] },
  })
}

// What happened -> its icon: { svg } names one of ACTIVITY_ICONS, { codicon }
// a glyph from the app's icon font.
const VERB_ICONS = {
  swapped: { svg: 'swap' },
  approved: { svg: 'allowance' },
  bridged: { svg: 'bridge' },
  sent: { codicon: 'arrow-up' },
  received: { codicon: 'arrow-down' },
  moved: { codicon: 'arrow-right' },
  staked: { codicon: 'arrow-circle-down' },
  lp_deposit: { codicon: 'arrow-circle-down' },
  unstaked: { codicon: 'arrow-circle-up' },
  lp_withdraw: { codicon: 'arrow-circle-up' },
  executed: { codicon: 'code' },
  run: { codicon: 'zap' },
  fill: { codicon: 'graph-line' },
}

/**
 * A failure, a run in progress and a pending transaction say so first.
 * Otherwise the icon says WHAT happened and the tint says WHO: Fello's own
 * actions keep the accent tint, money coming in is green.
 */
function markerOf(row) {
  if (row.status === 'failed') return { codicon: 'error', tone: 'is-bad' }
  if (row.status === 'running') return { tone: 'is-live' }
  if (row.status === 'pending') return { tone: 'is-pending' }
  const icon = VERB_ICONS[row.verb] || (row.actor === 'fello' ? VERB_ICONS.run : { codicon: 'circle-outline' })
  const tone = row.actor === 'fello' ? 'is-accent' : row.actor === 'incoming' || row.verb === 'received' ? 'is-good' : ''
  return { ...icon, tone }
}

const timeOf = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function dayLabel(iso, now = new Date()) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return 'Earlier'
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diff = Math.round((day(now) - day(date)) / 86400000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return date.toLocaleDateString(undefined, {
    weekday: diff < 7 ? 'long' : undefined,
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
  })
}

/** Page 1 + older pages + the fills inside the loaded span, newest first. */
function activityTimeline(first, older) {
  const pages = [first, ...older]
  const seen = new Set()
  const rows = []
  for (const page of pages) {
    for (const row of page.rows || []) {
      if (seen.has(row.key)) continue
      seen.add(row.key)
      rows.push(row)
    }
  }
  const last = pages[pages.length - 1]
  const more = !!last.next_cursor
  const oldest = rows.length ? Math.min(...rows.map((r) => Date.parse(r.at) || Infinity)) : -Infinity
  const fills = (first.fills || []).filter((f) => !more || (Date.parse(f.at) || 0) >= oldest)
  const all = [...rows, ...fills].sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0))
  const groups = []
  for (const row of all) {
    const label = dayLabel(row.at)
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, rows: [] })
    groups[groups.length - 1].rows.push(row)
  }
  return { groups, count: all.length, cursor: last.next_cursor || null }
}

function ActivityRow({ ctx, row }) {
  const marker = markerOf(row)
  const meta = [row.source, timeOf(row.at), row.chain_name].filter(Boolean).join(' · ')
  const resultClass = { positive: 'cf-up', negative: 'cf-down', error: 'cf-err-text' }[row.result && row.result.tone] || ''
  const body = [
    jsx(
      'span',
      {
        className: cn('cf-act-marker', marker.tone),
        title: row.status_label || undefined,
        'aria-label': row.status_label || undefined,
        children: marker.svg
          ? jsx(ActivityIcon, { name: marker.svg })
          : marker.codicon
            ? jsx(Codicon, { name: marker.codicon, size: 13 })
            : jsx('span', { className: 'cf-act-pulse' }),
      },
      'm',
    ),
    jsxs(
      'span',
      {
        className: 'cf-act-main',
        children: [
          jsx('span', { className: 'cf-act-sentence', children: row.sentence }),
          jsx('span', { className: 'cf-act-meta', children: row.status_label ? `${row.status_label} · ${meta}` : meta }),
        ],
      },
      'b',
    ),
    jsx('span', { className: cn('cf-act-result', resultClass), children: row.result ? row.result.text : '' }, 'r'),
  ]
  return row.tx_url
    ? jsx('button', {
        type: 'button',
        className: 'cf-act-row is-link',
        title: 'Open the transaction in a block explorer',
        onClick: () => ctx.os.openExternal(row.tx_url),
        children: body,
      })
    : jsx('div', { className: 'cf-act-row', children: body })
}

function ActivitySkeleton() {
  return jsx('div', {
    className: 'cf-card',
    style: { padding: 10 },
    'aria-busy': true,
    'aria-label': 'Loading activity',
    children: [0, 1, 2].map((i) =>
      jsxs(
        'div',
        {
          className: 'cf-act-row',
          children: [
            jsx('span', { className: 'cf-act-marker cf-skeleton' }),
            jsxs('span', {
              className: 'cf-act-main',
              children: [
                jsx('span', { className: 'cf-skeleton', style: { width: '85%', height: 11 } }),
                jsx('span', { className: 'cf-skeleton', style: { width: '45%', height: 9, marginTop: 5 } }),
              ],
            }),
          ],
        },
        i,
      ),
    ),
  })
}

function Activity({ ctx }) {
  const query = useQuery({
    queryKey: ['coinfello', 'activity'],
    queryFn: () => ctx.rest('/activity', { timeoutMs: 60 * 1000 }),
    refetchInterval: 60 * 1000,
    staleTime: 20 * 1000,
  })
  const [older, setOlder] = useState([])
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [olderError, setOlderError] = useState('')
  const first = query.data

  if (!first) {
    return query.isError
      ? jsxs('div', {
          className: 'cf-card cf-stack',
          children: [
            jsxs('div', {
              children: [
                jsx('div', { className: 'cf-err', children: 'Could not load your activity.' }),
                // A 404 here means the gateway predates this plugin version: its
                // Python routes load at gateway start, unlike this file.
                jsx('div', {
                  className: 'cf-hint',
                  children: /\b404\b|not found/i.test(String(query.error?.message || query.error || ''))
                    ? 'The Hermes gateway is running an older version of this plugin. Run "hermes gateway restart" in a terminal, then try again.'
                    : String(query.error?.message || query.error || 'Try again in a moment.'),
                }),
              ],
            }),
            jsx('div', { children: jsx(Button, { size: 'sm', variant: 'outline', loading: query.isFetching, onClick: () => query.refetch(), children: 'Try again' }) }),
          ],
        })
      : jsx(ActivitySkeleton, {})
  }
  if (first.ok === false) {
    return jsxs('div', {
      className: 'cf-card cf-stack',
      children: [
        first.unsupported
          ? jsx('div', { className: 'cf-hint', children: 'Activity needs a CoinFello server update. Until then, it is on CoinFello.' })
          : jsxs('div', {
              children: [
                jsx('div', { className: 'cf-err', children: 'Could not load your activity.' }),
                jsx('div', { className: 'cf-hint', children: first.error || 'Try again in a moment.' }),
              ],
            }),
        jsxs('div', {
          className: 'cf-links',
          children: [
            first.unsupported ? null : jsx(Button, { size: 'sm', variant: 'outline', onClick: () => query.refetch(), children: 'Try again' }),
            jsx(LinkPill, { ctx, url: first.activity_url, label: 'Open activity on CoinFello' }),
          ],
        }),
      ],
    })
  }

  const { groups, count, cursor } = activityTimeline(first, older)
  const loadOlder = async () => {
    setLoadingOlder(true)
    setOlderError('')
    try {
      const page = await ctx.rest(`/activity?before=${encodeURIComponent(cursor)}`, { timeoutMs: 60 * 1000 })
      if (!page || page.ok === false) setOlderError(errorOf(page, 'Could not load older activity'))
      else setOlder((pages) => [...pages, page])
    } catch (exc) {
      setOlderError(String(exc))
    } finally {
      setLoadingOlder(false)
    }
  }
  const notes = [
    first.error ? 'Some transactions could not be loaded. Try again in a moment.' : null,
    first.fills_error ? 'Hyperliquid fills could not be loaded.' : null,
    [first, ...older].some((p) => p.incomplete) ? 'Some older activity could not be loaded, so this list may be incomplete.' : null,
  ].filter(Boolean)

  return jsxs(Fragment, {
    children: [
      count === 0
        ? jsxs('div', {
            className: 'cf-card cf-act-empty',
            children: [
              jsx(Codicon, { name: 'history', size: 18 }),
              jsx('div', { className: 'cf-act-empty-title', children: 'Nothing yet' }),
              jsx('div', { className: 'cf-hint', children: 'Trades, transfers and what Fello does for you show up here.' }),
            ],
          })
        : jsx('div', {
            className: 'cf-card',
            style: { padding: 6 },
            children: groups.map((group) =>
              jsxs(
                'div',
                {
                  className: 'cf-act-day',
                  role: 'group',
                  'aria-label': group.label,
                  children: [
                    jsx('div', { className: 'cf-net-head', children: jsx('span', { className: 'cf-act-day-label', children: group.label }) }),
                    ...group.rows.map((row) => jsx(ActivityRow, { ctx, row }, row.key)),
                  ],
                },
                group.label,
              ),
            ),
          }),
      notes.map((note) => jsx('div', { className: 'cf-hint', style: { padding: '0 2px' }, children: note }, note)),
      olderError ? jsx('div', { className: 'cf-err', style: { padding: '0 2px' }, children: olderError }) : null,
      cursor
        ? jsx('div', {
            children: jsx(Button, { size: 'sm', variant: 'outline', className: 'w-full', loading: loadingOlder, disabled: loadingOlder, onClick: loadOlder, children: 'Show older' }),
          })
        : count > 0
          ? jsx('div', { className: 'cf-hint cf-center', children: 'That is the start of this wallet’s history.' })
          : null,
      jsx('div', { className: 'cf-links', children: jsx(LinkPill, { ctx, url: first.activity_url, label: 'Full activity' }) }),
    ],
  })
}

// -- send: form -> review (server-validated, single-use intent) -> result -------

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/

/* amount:start */
// The server takes a plain decimal with a leading digit ("0.001", not
// ".001"). Same rules as coinfello_core.normalize_amount, which the backend
// applies again; tests/amount_cases.json holds the two to one table. String
// operations only: Number() would round away digits a token has.
const AMOUNT_RE = /^([0-9]*)(?:\.([0-9]*))?$/
const AMOUNT_HINT = 'Enter an amount like 0.001'
const AMOUNT_ZERO = 'Enter an amount greater than 0'

function normalizeAmount(value) {
  const match = AMOUNT_RE.exec(String(value == null ? '' : value).trim())
  if (!match || !(match[1] || match[2])) return { amount: '', error: AMOUNT_HINT }
  const whole = match[1].replace(/^0+/, '') || '0'
  const fraction = (match[2] || '').replace(/0+$/, '')
  if (whole === '0' && !fraction) return { amount: '', error: AMOUNT_ZERO }
  return { amount: fraction ? `${whole}.${fraction}` : whole, error: '' }
}
/* amount:end */

function heldTokens(portfolio) {
  const rows = []
  for (const network of portfolio.networks || []) {
    for (const token of network.tokens || []) {
      rows.push({ ...token, chain_name: network.chain_name, key: `${token.chain_id}:${token.address}` })
    }
  }
  return rows
}

function Row({ label, value, mono }) {
  return jsxs('div', {
    className: 'flex items-start justify-between gap-3 text-xs',
    children: [
      jsx('span', { className: cn('shrink-0', muted), children: label }),
      jsx('span', { className: cn('min-w-0 text-right', mono && 'break-all font-mono'), children: value }),
    ],
  })
}

function Countdown({ seconds, onExpired }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    setLeft(seconds)
    const timer = setInterval(() => setLeft((value) => Math.max(0, value - 1)), 1000)
    return () => clearInterval(timer)
  }, [seconds])
  useEffect(() => {
    if (left === 0) onExpired()
  }, [left === 0])
  return jsx('span', { children: `${left}s` })
}

function SendFlow({ ctx, portfolio, onClose }) {
  const queryClient = useQueryClient()
  const tokens = heldTokens(portfolio)
  const [tokenKey, setTokenKey] = useState(tokens[0] ? tokens[0].key : '')
  const [amount, setAmount] = useState('')
  const [recipient, setRecipient] = useState('')
  const [stage, setStage] = useState('form') // form -> review -> result
  const [prepared, setPrepared] = useState(null)
  const [expired, setExpired] = useState(false)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const token = tokens.find((row) => row.key === tokenKey)

  const recipientValid = ADDRESS_RE.test(recipient.trim())
  const parsedAmount = normalizeAmount(amount)
  const canReview = !busy && token && !parsedAmount.error && recipientValid

  const review = async () => {
    if (!canReview) return
    setBusy(true)
    setError('')
    try {
      const response = await ctx.rest('/send/prepare', {
        method: 'POST',
        body: { chain_id: token.chain_id, token: token.address, amount: parsedAmount.amount, recipient: recipient.trim() },
      })
      if (!response || response.ok === false) setError(errorOf(response, 'Could not prepare the send'))
      else {
        setPrepared(response)
        setExpired(false)
        setStage('review')
      }
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    setBusy(true)
    setError('')
    try {
      const response = await ctx.rest('/intent/execute', {
        method: 'POST',
        body: { intent_id: prepared.intent_id },
        timeoutMs: 180000,
      })
      setResult(response || { ok: false, error: 'No response' })
      setStage('result')
      queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
    } catch (exc) {
      setResult({ ok: false, error: String(exc), unknown: true })
      setStage('result')
    } finally {
      setBusy(false)
    }
  }

  const header = jsxs('div', {
    className: row,
    children: [
      jsx('div', { className: 'font-medium', children: 'Send' }),
      jsx(Button, { variant: 'ghost', size: 'sm', onClick: onClose, children: 'Close' }),
    ],
  })

  if (stage === 'result') {
    const ok = result && result.ok
    const unknown = result && (result.unknown || result.outcome_unknown)
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        header,
        jsx('div', {
          className: cn('text-sm font-medium', ok ? up : unknown ? muted : down),
          children: ok ? 'Sent' : unknown ? 'Outcome unknown' : 'Not sent',
        }),
        ok
          ? jsx(Row, { label: 'Transaction', value: shortAddr(result.transaction_hash || ''), mono: true })
          : jsx('div', { className: 'text-xs', children: result && result.error }),
        unknown
          ? jsx('div', { className: cn('text-xs', muted), children: 'It may have gone through. Check the transaction or your CoinFello activity before trying again.' })
          : null,
        jsxs('div', {
          className: 'flex gap-2',
          children: [
            result && result.explorer_url
              ? jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(result.explorer_url), children: 'View transaction' })
              : null,
            jsx(Button, { size: 'sm', onClick: onClose, children: 'Done' }),
          ],
        }),
      ],
    })
  }

  if (stage === 'review' && prepared) {
    const summary = prepared.summary || {}
    const symbol = (summary.token && summary.token.symbol) || ''
    const usd = summary.valueUsd != null ? ` (~$${Number(summary.valueUsd).toFixed(2)})` : ''
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        header,
        jsxs('div', {
          className: 'flex flex-col gap-1.5 rounded-md border border-(--ui-stroke-secondary) p-2',
          children: [
            jsx(Row, { label: 'Send', value: `${summary.amount} ${symbol}${usd}` }),
            jsx(Row, { label: 'Network', value: summary.chainName }),
            jsx(Row, { label: 'To', value: summary.recipient, mono: true }),
            jsx(Row, { label: 'From', value: 'Automations wallet' }),
          ],
        }),
        jsx('div', {
          className: cn('text-[0.6875rem]', muted),
          children: 'This sends immediately from your automations wallet. Check the address: transactions cannot be reversed.',
        }),
        expired
          ? jsx('div', { className: cn('text-xs', down), children: 'This confirmation expired. Review again to refresh it.' })
          : jsxs('div', {
              className: cn('text-[0.6875rem]', muted),
              children: ['Confirmation valid for ', jsx(Countdown, { seconds: prepared.expires_in_seconds || 120, onExpired: () => setExpired(true) })],
            }),
        jsxs('div', {
          className: 'flex gap-2',
          children: [
            expired
              ? jsx(Button, { size: 'sm', loading: busy, onClick: review, children: 'Review again' })
              : jsx(Button, { size: 'sm', loading: busy, onClick: confirm, children: 'Confirm send' }),
            jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => setStage('form'), children: 'Back' }),
          ],
        }),
        error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
      ],
    })
  }

  return jsxs('form', {
    className: 'flex flex-col gap-2',
    onSubmit: (event) => {
      event.preventDefault()
      review()
    },
    children: [
      header,
      tokens.length === 0
        ? jsx('div', { className: cn('text-xs', muted), children: 'Nothing to send yet: fund the wallet first.' })
        : jsxs(Select, {
            value: tokenKey,
            onValueChange: setTokenKey,
            children: [
              jsx(SelectTrigger, { className: 'w-full', children: jsx(SelectValue, { placeholder: 'Token' }) }),
              jsx(SelectContent, {
                children: tokens.map((row) =>
                  jsx(SelectItem, { value: row.key, children: `${row.symbol} · ${row.chain_name} · ${row.balance_text}` }, row.key),
                ),
              }),
            ],
          }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Input, { value: amount, inputMode: 'decimal', placeholder: '0.00', onChange: (e) => setAmount(e.target.value) }),
          jsx(Button, { type: 'button', size: 'sm', variant: 'outline', disabled: !token, onClick: () => token && setAmount(token.balance), children: 'Max' }),
        ],
      }),
      amount.trim() && parsedAmount.error
        ? jsx('div', { className: 'cf-err', role: 'alert', children: parsedAmount.error })
        : null,
      jsx(Input, { value: recipient, placeholder: 'Recipient address (0x…)', spellCheck: false, onChange: (e) => setRecipient(e.target.value) }),
      recipient && !recipientValid
        ? jsx('div', { className: 'cf-err', children: 'Enter a full 0x address (42 characters).' })
        : null,
      jsx(Button, { type: 'submit', size: 'sm', loading: busy, disabled: !canReview, children: 'Review' }),
      error ? jsx('div', { className: cn('text-xs', down), children: error }) : null,
    ],
  })
}

// -- embedded views: CoinFello's real swap, Earn and portfolio UIs (/embed/*) ----
//
// One host for every embed: a sandboxed frame on <app><path>?theme=..., a
// short-lived token minted for its scope and handed over by postMessage, and
// its resize, link and result messages. The embeds speak the same protocol:
//   child  -> parent  {type: 'coinfello:embed-ready', version: 1, features?}
//                     (again, with the nonce, when its token is rejected)
//   parent -> child   {type: 'coinfello:embed-token', token, nonce}
//   child  -> parent  {type: 'coinfello:embed-resize', height}
//   child  -> parent  {type: 'coinfello:open-url', url}   allowlisted, 1/s
//   child  -> parent  {type: <the embed's resultType>, status, ...}
// An embed that advertises features: ['open-url'] opens its own links (its
// View button) through us; the sandbox has no allow-popups, so without that
// the pane offers a fallback View under the frame.
//
// Everything between the embed-host markers is plain JavaScript with no
// React or SDK import, so tests/embed_host.test.mjs can run it under node.

/* embed-host:start */
const EMBED_HEIGHT_MIN = 240
const EMBED_HEIGHT_MAX = 1200
const EMBED_HEIGHT_DEFAULT = 560
// Tokens live 15 minutes. A re-request within a minute of the last token
// means the session itself is gone (signed out, revoked).
const EMBED_REFRESH_GAP_MS = 60000
const EMBED_OPEN_GAP_MS = 1000
const EMBED_CHECK_TEXT = 'It may have gone through. Check the transaction or your CoinFello activity before trying again.'
const SWAP_FALLBACK_VIEW_TEXT = "The swap's View button can't open from inside Hermes. Use this one:"

// Hosts the embed may ask us to open (its links can't open themselves: the
// sandbox has no allow-popups). Block explorers from coinfello-web's
// BLOCK_EXPLORERS, plus Blockscan and LI.FI's bridge explorer. https only.
const EMBED_LINK_HOSTS = [
  'etherscan.io', 'optimistic.etherscan.io', 'sepolia.etherscan.io', 'arbiscan.io',
  'basescan.org', 'sepolia.basescan.org', 'bscscan.com', 'polygonscan.com',
  'lineascan.build', 'scrollscan.com', 'mantlescan.xyz', 'snowscan.xyz', 'uniscan.xyz',
  'katanascan.com', 'monadvision.com', 'explorer.inkonchain.com',
  'robinhoodchain.blockscout.com', 'blockscan.com', 'scan.li.fi',
]

function allowedEmbedLink(raw) {
  try {
    const url = new URL(String(raw))
    return url.protocol === 'https:' && EMBED_LINK_HOSTS.includes(url.hostname) ? url.toString() : null
  } catch {
    return null
  }
}

const EMBEDS = {
  swap: {
    scope: 'swap',
    path: '/embed/swap',
    resultType: 'coinfello:swap-result',
    title: 'Swap',
    frameTitle: 'CoinFello swap',
    mintError: 'Could not open swap',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Swap.',
    reloaded: 'The swap view reloaded. Reopen it to continue.',
  },
  earn: {
    scope: 'earn',
    path: '/embed/earn',
    resultType: 'coinfello:earn-result',
    title: 'Earn',
    frameTitle: 'CoinFello Earn',
    mintError: 'Could not open Earn',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Earn.',
    reloaded: 'The Earn view reloaded. Reopen it to continue.',
  },
  // Read-only: no result message. Opens in a main-area tab (EmbedWorkspace).
  portfolio: {
    scope: 'portfolio',
    path: '/embed/portfolio',
    resultType: '',
    title: 'Portfolio',
    frameTitle: 'CoinFello portfolio',
    mintError: 'Could not open Portfolio',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Portfolio.',
    reloaded: 'The Portfolio view reloaded. Reopen it to continue.',
  },
  // Read-only too: browse the catalog, a strategy's details, what is running.
  strategies: {
    scope: 'strategies',
    path: '/embed/strategies',
    resultType: '',
    title: 'Strategies',
    frameTitle: 'CoinFello strategies',
    mintError: 'Could not open Strategies',
    sessionEnded: 'Your CoinFello session ended. Sign in again, then reopen Strategies.',
    reloaded: 'The Strategies view reloaded. Reopen it to continue.',
  },
}

/** The frame's URL. `query` is the backend's already-escaped preselect
 * (coinfello_earn.frame_query); it always follows the theme. */
function embedFrameSrc({ appUrl, path, theme, query }) {
  const base = String(appUrl || '').replace(/\/+$/, '')
  const shade = theme === 'dark' ? 'dark' : 'light'
  return `${base}${path}?theme=${shade}${query ? `&${query}` : ''}`
}

/** ctx.rest options for minting this embed's token (POST /embed-token). */
const embedTokenRequest = (embed) => ({ method: 'POST', body: { scope: embed.scope } })

function clampEmbedHeight(height) {
  return Math.min(EMBED_HEIGHT_MAX, Math.max(EMBED_HEIGHT_MIN, Number(height)))
}

const embedErrorOf = (result, fallback) => (result && result.error) || fallback

/**
 * The parent half of the embed protocol, for one mount.
 *   frameWindow()         the frame's contentWindow (or null)
 *   post(target, message) posts to `target`, the window that asked
 *   mint()                resolves to /embed-token's answer for this scope
 *   nonce                 a per-mount secret, handed over with the first token
 *   openExternal(url)     opens an allowlisted link the embed asked for
 *   onResult(message, embedOpensLinks)  the embed's result message
 */
function createEmbedHost({
  embed, frameWindow, post, mint, nonce, now = () => Date.now(),
  openExternal = () => {}, onError, onResize, onResult,
}) {
  let tokenSent = false
  let lastSentAt = 0
  let lastOpenAt = -Infinity
  let opensLinks = false
  const sendToken = async (target) => {
    lastSentAt = now()
    const minted = await mint()
    if (!minted || minted.ok === false) {
      onError(embedErrorOf(minted, embed.mintError), minted || null)
      return
    }
    // A sandboxed (opaque-origin) frame can only be addressed with '*'; the
    // token is short-lived and good only for this embed's scope.
    post(target, { type: 'coinfello:embed-token', token: minted.token, nonce })
  }
  /** Handles one window message event; false when it was not ours. */
  const handle = async (event) => {
    const own = frameWindow()
    // Only our own frame speaks this protocol; everything else is ignored.
    if (!own || !event || event.source !== own) return false
    const message = (event.data && typeof event.data === 'object') ? event.data : {}
    if (message.type === 'coinfello:embed-ready') {
      opensLinks = Array.isArray(message.features) && message.features.includes('open-url')
      if (!tokenSent) {
        tokenSent = true
        await sendToken(own)
      } else if (message.nonce === nonce) {
        // Minting again so soon would loop on a dead session: stop and say so.
        if (now() - lastSentAt < EMBED_REFRESH_GAP_MS) {
          onError(embed.sessionEnded, null)
          return true
        }
        await sendToken(own) // an expired token, from the same document
      } else {
        // A document the frame navigated to never saw the nonce: no token.
        onError(embed.reloaded, null)
      }
    } else if (message.type === 'coinfello:embed-resize' && Number(message.height) > 0) {
      onResize(clampEmbedHeight(message.height))
    } else if (message.type === 'coinfello:open-url') {
      // The embed's own links: only allowlisted https explorers, 1/s.
      const url = allowedEmbedLink(message.url)
      const at = now()
      if (url && at - lastOpenAt >= EMBED_OPEN_GAP_MS) {
        lastOpenAt = at
        openExternal(url)
      }
    } else if (embed.resultType && message.type === embed.resultType) {
      onResult(message, opensLinks)
    }
    return true
  }
  return { handle }
}

const TX_HASH_RE = /^0x[0-9a-fA-F]{64}$/
const txExplorerUrl = (hash) => (typeof hash === 'string' && TX_HASH_RE.test(hash) ? `https://blockscan.com/tx/${hash}` : '')

/**
 * Swap's result. The widget shows its own success row and View button; the
 * pane adds nothing, except a fallback View for an embed that cannot open
 * links through us (it does not advertise 'open-url').
 */
function swapOutcome(message, embedOpensLinks) {
  if (!message || message.status !== 'success' || embedOpensLinks) return null
  const explorerUrl = txExplorerUrl(message.transactionHash)
  return explorerUrl ? { tone: 'muted', title: '', detail: SWAP_FALLBACK_VIEW_TEXT, explorerUrl } : null
}

/**
 * Earn's result. "Nothing was sent" only when the embed says it was
 * cancelled or failed AND names no transaction; anything else that is not a
 * clean success (unknown, outcomeUnknown, a failure with a hash, a status we
 * do not know) asks the person to check, never to retry. As for swap, the
 * pane's View button is only for an embed that cannot open links itself,
 * and a clean success from one that can is left to the widget.
 */
function earnOutcome(message, embedOpensLinks) {
  if (!message || typeof message !== 'object') return null
  const hash = typeof message.transactionHash === 'string' && TX_HASH_RE.test(message.transactionHash) ? message.transactionHash : ''
  const explorerUrl = hash && !embedOpensLinks ? txExplorerUrl(hash) : ''
  const error = typeof message.error === 'string' ? message.error.trim().slice(0, 300) : ''
  const unknown = message.outcomeUnknown === true
  if (message.status === 'success' && !unknown) {
    return embedOpensLinks ? null : { tone: 'good', title: 'Deposit submitted.', detail: '', explorerUrl }
  }
  if (!hash && !unknown && message.status === 'cancelled') {
    return { tone: 'muted', title: 'Deposit cancelled.', detail: 'Nothing was sent.', explorerUrl: '' }
  }
  if (!hash && !unknown && message.status === 'failed') {
    return { tone: 'bad', title: 'Deposit failed.', detail: error ? `${error} Nothing was sent.` : 'Nothing was sent.', explorerUrl: '' }
  }
  return { tone: 'muted', title: 'Deposit status unknown. Check status.', detail: error ? `${error} ${EMBED_CHECK_TEXT}` : EMBED_CHECK_TEXT, explorerUrl }
}
/* embed-host:end */

const EMBED_OUTCOMES = { swap: swapOutcome, earn: earnOutcome }
const EARN_OPEN_EVENT = 'plugin.coinfello.earn.open'

/** createEmbedHost for one mounted frame of `kind`. */
function useEmbedHost({ ctx, kind, frameRef, mount, onResult }) {
  const [error, setError] = useState('')
  const [height, setHeight] = useState(EMBED_HEIGHT_DEFAULT)
  const onResultRef = useRef(onResult)
  onResultRef.current = onResult

  useEffect(() => {
    const embed = EMBEDS[kind]
    const bridge = createEmbedHost({
      embed,
      // Per-mount secret: later token requests must echo it.
      nonce: crypto.randomUUID(),
      frameWindow: () => (frameRef.current ? frameRef.current.contentWindow : null),
      post: (target, message) => target.postMessage(message, '*'),
      mint: () => ctx.rest('/embed-token', embedTokenRequest(embed)),
      openExternal: (url) => ctx.os.openExternal(url),
      onError: setError,
      onResize: setHeight,
      onResult: (message, embedOpensLinks) => onResultRef.current && onResultRef.current(message, embedOpensLinks),
    })
    const onMessage = (event) => {
      bridge.handle(event)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [mount, ctx, kind, frameRef])

  return { error, setError, height }
}

/** An embed that could not open, with the one way forward. */
function EmbedNotice({ error, onReopen, style }) {
  return jsxs('div', {
    className: 'cf-notice is-static',
    role: 'alert',
    style,
    children: [
      jsx(Codicon, { name: 'warning', size: 14 }),
      jsx('span', { className: 'cf-notice-text', children: error }),
      jsx(Button, { size: 'sm', variant: 'outline', onClick: onReopen, children: 'Reopen' }),
    ],
  })
}

const OUTCOME_TONES = { good: 'cf-ok', bad: 'cf-err', muted: 'cf-muted' }

/** What the pane adds under an embed after its result (see swapOutcome / earnOutcome). */
function EmbedOutcome({ ctx, outcome }) {
  return jsxs('div', {
    className: 'cf-embed-outcome',
    role: 'status',
    children: [
      outcome.title ? jsx('div', { className: cn('cf-embed-outcome-title', OUTCOME_TONES[outcome.tone]), children: outcome.title }) : null,
      outcome.detail || outcome.explorerUrl
        ? jsxs('div', {
            className: 'cf-embed-outcome-row',
            children: [
              outcome.detail ? jsx('span', { className: 'cf-hint', children: outcome.detail }) : null,
              outcome.explorerUrl
                ? jsx(Button, {
                    size: 'sm',
                    variant: 'outline',
                    onClick: () => ctx.os.openExternal(outcome.explorerUrl),
                    children: jsxs(Fragment, { children: ['View transaction', jsx(Codicon, { name: 'link-external', size: 12 })] }),
                  })
                : null,
            ],
          })
        : null,
    ],
  })
}

/** Swap or Earn, in the pane. */
function EmbedView({ ctx, appUrl, kind, query, onClose }) {
  const embed = EMBEDS[kind]
  const queryClient = useQueryClient()
  const frameRef = useRef(null)
  const [mount, setMount] = useState(0)
  const [outcome, setOutcome] = useState(null)

  const dark = document.documentElement.classList.contains('dark')
  const src = embedFrameSrc({ appUrl, path: embed.path, theme: dark ? 'dark' : 'light', query })

  const { error, setError, height } = useEmbedHost({
    ctx,
    kind,
    frameRef,
    mount,
    onResult: (message, embedOpensLinks) => {
      queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
      const next = EMBED_OUTCOMES[kind](message, embedOpensLinks)
      if (next) setOutcome(next)
    },
  })
  const reopen = () => {
    setError('')
    setOutcome(null)
    setMount(mount + 1)
  }

  return jsxs(Fragment, {
    children: [
      jsxs('div', {
        className: 'cf-subhead',
        children: [
          jsx('button', { type: 'button', className: 'cf-icon-btn', 'aria-label': 'Back', title: 'Back', onClick: onClose, children: jsx(Codicon, { name: 'arrow-left', size: 16 }) }),
          jsx('span', { className: 'cf-subhead-title', children: embed.title }),
        ],
      }),
      error ? jsx(EmbedNotice, { error, onReopen: reopen }) : null,
      jsx(SandboxedFrame, {
        key: mount,
        ref: frameRef,
        src,
        title: embed.frameTitle,
        sandbox: 'allow-scripts allow-forms',
        className: 'cf-embed-frame',
        style: { height },
      }),
      // Under the frame, next to the widget's own result row.
      outcome ? jsx(EmbedOutcome, { ctx, outcome }) : null,
    ],
  })
}

/**
 * The model's coinfello_show_card(card="earn_deposit") on desktop leaves an
 * "open Earn" request in the backend (coinfello_earn). Open it here once:
 * at the event, or at the next poll on Hermes builds without events.
 */
function useEarnRequests(ctx, enabled, open) {
  const queryClient = useQueryClient()
  const request = useQuery({
    queryKey: ['coinfello', 'earn-request'],
    queryFn: () => ctx.rest('/earn/request'),
    enabled,
    refetchInterval: 20 * 1000,
  })
  useEffect(() => {
    if (!enabled || typeof ctx.onEvent !== 'function') return undefined
    return ctx.onEvent(EARN_OPEN_EVENT, () => queryClient.invalidateQueries({ queryKey: ['coinfello', 'earn-request'] }))
  }, [ctx, queryClient, enabled])
  const pending = enabled && request.data && request.data.ok !== false ? request.data.request : null
  const pendingId = pending ? pending.id : ''
  useEffect(() => {
    if (!pending) return
    open(pending)
    ctx.rest(`/earn/request/${pending.id}/consume`, { method: 'POST', body: {} })
      .catch(() => {})
      .finally(() => queryClient.invalidateQueries({ queryKey: ['coinfello', 'earn-request'] }))
  }, [pendingId])
}

// -- in-app portfolio: coinfello-web /embed/portfolio in a main-area tab ------
//
// The browser link opens the full web app, whose wallet layer reconnects a
// browser-extension wallet (MetaMask) and can sign in as the wrong account.
// The embed shows this plugin's own account: a 15-minute, read-only,
// portfolio-scoped token, no cookies, no wallet connection.

// Read-only views that open as a main-area tab, one tab per kind.
const TABS = {
  portfolio: { id: 'coinfello-portfolio', title: 'CoinFello portfolio' },
  strategies: { id: 'coinfello-strategies', title: 'CoinFello strategies' },
}
const closeTab = {}

function EmbedWorkspace({ ctx, appUrl, kind }) {
  const embed = EMBEDS[kind]
  const frameRef = useRef(null)
  const [mount, setMount] = useState(0)
  const [dark] = useState(() => document.documentElement.classList.contains('dark'))
  const { error, setError } = useEmbedHost({ ctx, kind, frameRef, mount })
  const reopen = () => {
    setError('')
    setMount(mount + 1)
  }
  return jsxs('div', {
    className: 'cf',
    style: { padding: 0, gap: 0, overflow: 'hidden' },
    children: [
      jsxs('header', {
        className: 'cf-header',
        style: { padding: '8px 14px', borderBottom: '1px solid var(--ui-stroke-tertiary)' },
        children: [
          jsxs('div', {
            className: 'flex items-center gap-2',
            children: [jsx(Logo, {}), jsx('span', { className: 'cf-subhead-title', children: embed.title })],
          }),
          jsx('button', {
            type: 'button',
            className: 'cf-icon-btn',
            title: 'Reload',
            'aria-label': `Reload ${embed.title.toLowerCase()}`,
            onClick: reopen,
            children: jsx(Codicon, { name: 'refresh', size: 15 }),
          }),
        ],
      }),
      error ? jsx(EmbedNotice, { error, onReopen: reopen, style: { margin: 12, width: 'auto' } }) : null,
      jsx(SandboxedFrame, {
        key: mount,
        ref: frameRef,
        src: embedFrameSrc({ appUrl, path: embed.path, theme: dark ? 'dark' : 'light' }),
        title: embed.frameTitle,
        sandbox: 'allow-scripts allow-forms',
        style: { flex: 1, width: '100%', minHeight: 0, border: 0 },
      }),
    ],
  })
}

/** True when this desktop can dock a plugin tab into the main area. */
const canOpenTabs = () => typeof host?.openWorkspace === 'function'

function openEmbedTab(ctx, appUrl, kind) {
  const tab = TABS[kind]
  closeTab[kind] = host.openWorkspace(tab.id, {
    title: tab.title,
    minWidth: '420px',
    render: () => jsx(EmbedWorkspace, { ctx, appUrl, kind }),
    onClose: () => {
      delete closeTab[kind]
    },
  })
}

/** Sign-out closes every tab: they show the account that just left. */
function closeEmbedTabs() {
  for (const kind of Object.keys(closeTab)) {
    const close = closeTab[kind]
    delete closeTab[kind]
    close()
  }
}

// -- signed-out: Hermes's own OAuth sign-in -----------------------------------------
//
// CoinFello sign-in is the plugin's `oauth:` entry: the human runs
// `hermes auth add coinfello:coinfello` once in a terminal (Hermes refuses it
// from the pane, an agent or a gateway), approves on CoinFello in their
// browser, and Hermes keeps the grant. The pane never sees a token: it shows
// the command and checks every few seconds whether requests now go through.
function HermesSignIn({ ctx, status, refresh }) {
  const command = status.sign_in_command || 'hermes auth add coinfello:coinfello'
  const envName = status.client_id_env || 'COINFELLO_OAUTH_CLIENT_ID'
  const envLine = `echo '${envName}=${status.client_id || 'coinfello-hermes'}' >> "$(hermes config env-path)"`

  useEffect(() => {
    const timer = setInterval(() => refresh(), 5000)
    return () => clearInterval(timer)
  }, [refresh])

  const commandRow = (text, label) =>
    jsxs('div', {
      className: cn(row, 'rounded-md border border-(--ui-stroke-secondary) px-2 py-1.5'),
      children: [
        jsx('code', { className: 'min-w-0 flex-1 truncate font-mono text-[0.6875rem] select-all', children: text }),
        jsx(CopyButton, { text, appearance: 'icon', label }),
      ],
    })

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx('div', {
        className: cn('text-xs', muted),
        children:
          'Sign in once from a terminal on this computer. It opens CoinFello in your browser, where you choose what your agent may do: read only, or trade up to a daily limit.',
      }),
      commandRow(command, 'Copy sign-in command'),
      status.account_hint
        ? jsx('div', { className: cn('text-[0.6875rem]', muted), children: `Last signed in as ${status.account_hint}` })
        : null,
      jsx('div', {
        className: cn('text-[0.6875rem]', muted),
        children: `If Hermes says ${envName} is missing, run this first:`,
      }),
      commandRow(envLine, 'Copy client id command'),
      jsxs('div', {
        className: row,
        children: [
          jsx('span', { className: cn('animate-pulse text-xs', muted), children: 'Waiting for sign-in…' }),
          jsx(Button, { size: 'sm', variant: 'ghost', onClick: refresh, children: 'Check now' }),
        ],
      }),
      status.error ? jsx('div', { className: cn('text-xs', down), children: status.error }) : null,
    ],
  })
}

// The session's access and its daily limit, adjustable in
// place: lowering applies at once; a raise (or read-only -> trading) opens a
// one-click approval on CoinFello in the browser. Same session either way.
const LIMIT_PRESETS = [50, 250, 1000]

const money = (value) => {
  const n = Number(value)
  const cents = Number.isInteger(n) ? 0 : 2
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: cents, maximumFractionDigits: cents })}`
}

function LimitEditor({ current, busy, onSave, onCancel }) {
  const preset = current != null && LIMIT_PRESETS.includes(current)
  const [choice, setChoice] = useState(current == null ? 'read' : preset ? String(current) : 'custom')
  const [custom, setCustom] = useState(current != null && !preset ? String(current) : '')
  const isCustom = choice === 'custom'
  const value = choice === 'read' ? null : isCustom ? Number(custom) : Number(choice)
  const valid = choice === 'read' || (Number.isFinite(value) && value > 0)
  const raising = value != null && (current == null || value > current)

  const option = (key, label) =>
    jsx(Button, {
      key,
      type: 'button',
      size: 'sm',
      variant: choice === key ? 'secondary' : 'outline',
      onClick: () => setChoice(key),
      children: label,
    })

  return jsxs('form', {
    className: 'flex flex-col gap-2',
    onSubmit: (event) => {
      event.preventDefault()
      if (valid && !busy) onSave(value)
    },
    children: [
      jsxs('div', {
        className: 'flex flex-wrap gap-1',
        children: [
          option('read', 'Read only'),
          ...LIMIT_PRESETS.map((amount) => option(String(amount), `${money(amount)}/day`)),
          option('custom', 'Custom'),
        ],
      }),
      isCustom
        ? jsx(Input, { value: custom, inputMode: 'decimal', autoFocus: true, placeholder: 'Daily limit in USD, e.g. 500', onChange: (e) => setCustom(e.target.value.replace(/[^0-9.]/g, '')) })
        : null,
      jsx('div', {
        className: cn('text-[0.6875rem]', muted),
        children: raising
          ? 'Raising opens a one-click approval on CoinFello in your browser. Same session, no new sign-in.'
          : 'Applies right away. Same session, no new sign-in.',
      }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Button, { type: 'submit', size: 'sm', loading: busy, disabled: !valid, children: raising ? 'Continue in browser' : 'Save' }),
          jsx(Button, { type: 'button', size: 'sm', variant: 'ghost', onClick: onCancel, children: 'Cancel' }),
        ],
      }),
    ],
  })
}

/** Polls a raise that waits on the human's browser approval, wherever the
 *  user is in the pane, and reports how it settled. */
function useLimitPoll(ctx, pendingUrl, refresh, report) {
  useEffect(() => {
    if (!pendingUrl) return undefined
    const timer = setInterval(async () => {
      try {
        const result = await ctx.rest('/limit/poll', { method: 'POST', body: {} })
        if (!result || result.status === 'pending') return
        if (result.status === 'approved') report(result.user_message || 'Allowance updated.')
        else if (result.status === 'denied') report('The change was denied. Your allowance is unchanged.')
        else if (result.status === 'expired') report('The approval link expired. Your allowance is unchanged.')
        refresh()
      } catch {
        // transient: keep polling
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [pendingUrl, ctx, refresh, report])
}

/**
 * Whole-number percent that never claims 0% or 100% when that is not exact,
 * so a $0.10 trade on a $100 allowance reads ">99% left", not "100% left".
 */
function percentText(part, whole) {
  if (!(whole > 0)) return '0%'
  const p = (part / whole) * 100
  if (p <= 0) return '0%'
  if (p >= 100) return '100%'
  if (p < 1) return '<1%'
  if (p > 99) return '>99%'
  return `${Math.round(p)}%`
}

/**
 * What is left to trade today. The headline is the amount LEFT (not the
 * limit), and the bar is a fuel gauge: the filled part is what is left and
 * empties as trades spend it, with both segments labelled in $ and %.
 */
function AllowanceLeft({ limit, remaining, spent }) {
  const left = Math.max(0, Math.min(limit, remaining))
  const used = spent != null && Number.isFinite(Number(spent)) ? Math.max(0, Number(spent)) : Math.max(0, limit - left)
  const leftShare = limit > 0 ? (left / limit) * 100 : 0
  return jsxs('div', {
    className: 'cf-allow-left',
    children: [
      jsxs('div', {
        className: 'cf-allow-figure',
        children: [money(left), jsx('small', { children: 'left to trade today' })],
      }),
      jsx('div', {
        className: 'cf-hint',
        children: `${percentText(left, limit)} of your ${money(limit)} daily allowance`,
      }),
      jsx('div', {
        className: cn('cf-meter', left <= 0 && 'is-empty'),
        role: 'meter',
        'aria-valuemin': 0,
        'aria-valuemax': limit,
        'aria-valuenow': left,
        'aria-valuetext': `${money(left)} left of ${money(limit)} (${percentText(left, limit)})`,
        'aria-label': 'Allowance left to trade today',
        children: jsx('span', { style: { width: `${leftShare}%` } }),
      }),
      jsxs('div', {
        className: 'cf-meter-legend',
        children: [
          jsxs('span', {
            children: [
              jsx('i', { className: 'cf-swatch is-left', 'aria-hidden': true }),
              jsx('b', { children: money(left) }),
              ` left · ${percentText(left, limit)}`,
            ],
          }),
          jsxs('span', {
            children: [
              jsx('i', { className: 'cf-swatch is-used', 'aria-hidden': true }),
              jsx('b', { children: money(used) }),
              ` used · ${percentText(used, limit)}`,
            ],
          }),
        ],
      }),
      jsx('div', { className: 'cf-hint', children: 'Counts trades from the last 24 hours, so it refills as they age out.' }),
    ],
  })
}

function TradingAllowance({ ctx, status, refresh, message, setMessage }) {
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const pendingUrl = status.pending_limit_change_url

  if (!status.access || status.access === 'unknown') {
    return jsx('div', { className: 'cf-hint', children: 'This CoinFello server does not report trading access yet.' })
  }
  const current = status.access === 'trade' ? Number(status.daily_limit_usd) : null
  const remaining = status.remaining_today_usd != null ? Number(status.remaining_today_usd) : null

  const save = async (limit) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const result = await ctx.rest('/limit', { method: 'POST', body: { limit_usd: limit } })
      if (!result || result.ok === false) setError(errorOf(result, 'Could not change the allowance'))
      else if (result.status === 'approval_required') ctx.os.openExternal(result.approval_url)
      else setMessage(result.user_message || 'Allowance updated.')
      setEditing(false)
      refresh()
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }

  const cancelPending = async () => {
    await ctx.rest('/limit/cancel', { method: 'POST', body: {} })
    refresh()
  }

  const trading = current != null
  return jsxs('div', {
    className: 'cf-stack',
    children: [
      jsxs('div', {
        children: [
          jsxs('div', {
            className: 'cf-allow-top',
            children: [
              jsxs('span', {
                className: 'cf-allow-state',
                children: [jsx('span', { className: cn('cf-dot', trading ? 'is-on' : 'is-warn') }), trading ? 'Trading enabled' : 'Read-only'],
              }),
              !editing && !pendingUrl
                ? jsx(Button, {
                    size: 'sm',
                    variant: trading ? 'outline' : 'default',
                    onClick: () => (status.can_adjust_limit ? setEditing(true) : save(null)),
                    children: trading ? 'Change' : 'Enable trading',
                  })
                : null,
            ],
          }),
          trading && remaining == null
            ? jsxs('div', { className: 'cf-allow-figure', children: [money(current), jsx('small', { children: 'per day' })] })
            : null,
          trading && remaining != null ? jsx(AllowanceLeft, { limit: current, remaining, spent: status.spent_today_usd }) : null,
        ],
      }),
      !trading && !editing && !pendingUrl
        ? jsx('div', { className: 'cf-hint', children: 'Balances and quotes work. To send or swap from Hermes, set a daily allowance.' })
        : null,
      editing ? jsx(LimitEditor, { current, busy, onSave: save, onCancel: () => setEditing(false) }) : null,
      pendingUrl
        ? jsxs('div', {
            className: 'cf-stack',
            children: [
              jsx('div', {
                className: 'cf-hint',
                children: `Approve ${status.pending_limit_requested == null ? 'read-only' : `${money(status.pending_limit_requested)}/day`} on CoinFello in your browser (sign in there first if it asks).`,
              }),
              jsxs('div', {
                className: row,
                children: [
                  jsx('span', { className: 'cf-hint animate-pulse', children: 'Waiting for approval…' }),
                  jsxs('div', {
                    className: 'flex gap-1',
                    children: [
                      jsx(Button, { size: 'sm', variant: 'outline', onClick: () => ctx.os.openExternal(pendingUrl), children: 'Reopen' }),
                      jsx(Button, { size: 'sm', variant: 'ghost', onClick: cancelPending, children: 'Cancel' }),
                    ],
                  }),
                ],
              }),
            ],
          })
        : null,
      !editing && !pendingUrl && status.can_adjust_limit
        ? jsx('div', { className: 'cf-hint', children: 'You can change this here any time. Your session stays signed in; raising it asks for a one-click approval in your browser.' })
        : null,
      message ? jsx('div', { className: 'cf-ok', children: message }) : null,
      error ? jsx('div', { className: 'cf-err', children: error }) : null,
    ],
  })
}

function SettingsRow({ label, children }) {
  return jsxs('div', { className: 'cf-row', children: [jsx('span', { className: 'cf-row-label', children: label }), jsx('span', { className: 'cf-row-value', children })] })
}

function hostOf(url) {
  try {
    return new URL(url).host
  } catch {
    return url || ''
  }
}

const THEMES = [
  { value: 'hermes', label: 'Hermes theme', description: 'Buttons and highlights use your Hermes accent color.', swatch: 'var(--dt-primary)' },
  { value: 'coinfello', label: 'CoinFello theme', description: "Buttons and highlights use CoinFello's yellow.", swatch: 'var(--cf-brand)' },
]

/** Settings > Appearance: one of two named themes, as a native radio group. */
function ThemePicker({ brand, setBrand }) {
  const selected = brand ? 'coinfello' : 'hermes'
  return jsxs('fieldset', {
    className: 'cf-radios',
    children: [
      jsx('legend', { className: 'cf-sr-only', children: 'Pane theme' }),
      ...THEMES.map((theme) =>
        jsxs(
          'label',
          {
            className: cn('cf-radio', selected === theme.value && 'is-checked'),
            children: [
              jsx('input', {
                type: 'radio',
                name: 'coinfello-theme',
                value: theme.value,
                checked: selected === theme.value,
                onChange: () => setBrand(theme.value === 'coinfello'),
              }),
              jsxs('span', {
                className: 'cf-radio-text',
                children: [
                  jsx('span', { className: 'cf-radio-label', children: theme.label }),
                  jsx('span', { className: 'cf-hint', children: theme.description }),
                ],
              }),
              jsx('span', { className: 'cf-radio-swatch', style: { background: theme.swatch }, 'aria-hidden': true }),
            ],
          },
          theme.value,
        ),
      ),
    ],
  })
}

function Settings({ ctx, status, refresh, onBack, onSignOut, message, setMessage, brand, setBrand }) {
  const who = status.signed_in_as || status.email || ''
  return jsxs(Fragment, {
    children: [
      jsxs('div', {
        className: 'cf-subhead',
        children: [
          jsx('button', { type: 'button', className: 'cf-icon-btn', 'aria-label': 'Back', title: 'Back', onClick: onBack, children: jsx(Codicon, { name: 'arrow-left', size: 16 }) }),
          jsx('span', { className: 'cf-subhead-title', children: 'Settings' }),
        ],
      }),
      jsxs('section', {
        className: 'cf-section',
        children: [
          jsx('div', { className: 'cf-section-head', children: jsx('span', { className: 'cf-section-title', children: 'Trading allowance' }) }),
          jsx('div', { className: 'cf-card', children: jsx(TradingAllowance, { ctx, status, refresh, message, setMessage }) }),
        ],
      }),
      jsxs('section', {
        className: 'cf-section',
        children: [
          jsx('div', { className: 'cf-section-head', children: jsx('span', { className: 'cf-section-title', children: 'Account' }) }),
          jsxs('div', {
            className: 'cf-card cf-rows',
            children: [
              jsxs('div', {
                className: 'cf-row',
                children: [
                  jsxs('div', {
                    className: 'cf-account',
                    children: [
                      jsx('span', { className: 'cf-avatar', 'aria-hidden': true, children: (who[0] || 'C').toUpperCase() }),
                      jsxs('div', {
                        className: 'min-w-0',
                        children: [
                          jsx('div', { className: 'cf-account-name', title: who || undefined, children: who || 'CoinFello account' }),
                          jsx('div', { className: 'cf-hint', children: status.expires_at ? `Session renews automatically · ${shortDate(status.expires_at)}` : 'Signed in' }),
                        ],
                      }),
                    ],
                  }),
                ],
              }),
              jsx('div', {
                className: 'cf-row',
                children: jsxs('button', {
                  type: 'button',
                  className: 'cf-danger-btn',
                  onClick: onSignOut,
                  children: [jsx(Codicon, { name: 'sign-out', size: 14 }), who ? 'Sign out (not you?)' : 'Sign out'],
                }),
              }),
            ],
          }),
        ],
      }),
      jsxs('section', {
        className: 'cf-section',
        children: [
          jsx('div', { className: 'cf-section-head', children: jsx('span', { className: 'cf-section-title', children: 'Appearance' }) }),
          jsx('div', { className: 'cf-card', children: jsx(ThemePicker, { brand, setBrand }) }),
        ],
      }),
      jsxs('section', {
        className: 'cf-section',
        children: [
          jsx('div', { className: 'cf-section-head', children: jsx('span', { className: 'cf-section-title', children: 'Connection' }) }),
          jsxs('div', {
            className: 'cf-card cf-rows',
            children: [
              jsx(SettingsRow, { label: 'Server', children: jsx('span', { className: 'cf-mono', title: status.endpoint, children: hostOf(status.endpoint) }) }),
              status.app_url
                ? jsx('div', { className: 'cf-row', children: jsx(LinkPill, { ctx, url: status.app_url, label: 'Open CoinFello' }) })
                : null,
            ],
          }),
        ],
      }),
    ],
  })
}


// -- MCP App cards: the host half of the MCP Apps bridge -------------------------
//
// The agent's coinfello_show_card stores a card record in the backend and
// emits plugin.coinfello.card.shown. The pane fetches /cards/{id} (a ready
// data: document with its CSP, the tool input and the raw tool result),
// mounts it in a SandboxedFrame (allow-scripts only: opaque origin, no
// storage, no popups) and answers the card's JSON-RPC.
//
// Everything between the card-bridge markers is plain JavaScript with no
// React or SDK import, so tests/card_bridge.test.mjs can run it under node.

/* card-bridge:start */
const CARD_PROTOCOL_VERSION = '2026-01-26'
const CARD_HEIGHT_MIN = 120
const CARD_HEIGHT_MAX = 1400
// Cards target ~480px; a card that overflows the ~300px pane is laid out
// wider (up to this) and scaled down to fit, never cut off.
const CARD_LAYOUT_MAX = 560
const CARD_CALLS_PER_MINUTE = 30
const CARD_CANCELLED_TEXT = 'Cancelled in Hermes. Nothing was sent.'

// The same tables as coinfello_cards.py (a test keeps them in sync): what a
// card may relay is checked here AND in the backend.
//
// The yield and earn deposit cards share one document that draws either, so
// a row's Deposit (show_earn_deposit_card) and Browse yields (show_yield_card)
// come back through the bridge like any tools/call and the card redraws in
// place from the result's structuredContent. The frame, its record and its
// allowlist stay those of the card that was shown; nothing is remounted, and
// the model's Earn view routing (coinfello_show_card) is never involved.
const CARD_ALWAYS_RELAYED = ['whoami']
const CARD_RETRYABLE_TOOLS = [
  'get_activity', 'get_balances', 'get_deposit_options', 'get_gas_price',
  'get_lp_positions', 'get_needs_attention', 'get_open_orders', 'get_positions',
  'get_prices', 'get_quote', 'get_transfer_status', 'get_yields',
  'prepare_send', 'prepare_swap', 'whoami',
]
const CARD_NEVER_RELAYED = [
  'sign_out', 'fello_chat', 'fello_job_status', 'start_browser_sign_in',
  'renew_session', 'create_embed_token', 'set_daily_limit', 'start_limit_change',
  'get_limit_change', 'sign_in_card_status', 'show_sign_in_card',
]
const CARD_TOOLS = {
  'ui://coinfello/portfolio-card.html': { tool: 'show_portfolio_card', relay: [], confirm: [] },
  'ui://coinfello/status-card.html': { tool: 'show_status_card', relay: [], confirm: [] },
  'ui://coinfello/quote-card.html': { tool: 'show_quote_card', relay: ['prepare_swap', 'prepare_send', 'show_status_card'], confirm: ['execute_intent'] },
  'ui://coinfello/automations-card.html': { tool: 'show_automations_card', relay: ['pause_automation'], confirm: ['cancel_automation'] },
  'ui://coinfello/needs-you-card.html': { tool: 'show_needs_you_card', relay: [], confirm: [] },
  'ui://coinfello/error-card.html': { tool: 'show_error_card', relay: [], confirm: [] },
  'ui://coinfello/fund-card.html': { tool: 'show_fund_card', relay: [], confirm: [] },
  'ui://coinfello/yield-card.html': { tool: 'show_yield_card', relay: ['show_earn_deposit_card', 'prepare_earn_deposit', 'show_status_card'], confirm: ['execute_intent'] },
  'ui://coinfello/lp-ranges-card.html': { tool: 'show_lp_ranges_card', relay: [], confirm: [] },
  'ui://coinfello/perp-card.html': { tool: 'show_perp_card', relay: [], confirm: [] },
  'ui://coinfello/send-card.html': { tool: 'show_send_card', relay: ['prepare_send', 'show_status_card'], confirm: ['execute_intent'] },
  'ui://coinfello/dca-card.html': { tool: 'show_dca_card', relay: ['prepare_dca', 'show_status_card'], confirm: ['execute_intent'] },
  'ui://coinfello/earn-deposit-card.html': { tool: 'show_earn_deposit_card', relay: ['prepare_earn_deposit', 'show_yield_card', 'show_status_card'], confirm: ['execute_intent'] },
  'ui://coinfello/spend-limit-card.html': { tool: 'show_spend_limit_card', relay: ['prepare_spend_limit'], confirm: ['execute_intent'] },
}

/** 'relay', 'confirm' (the human decides first) or 'deny'. */
function cardToolDecision(uri, tool, structured) {
  const card = Object.prototype.hasOwnProperty.call(CARD_TOOLS, uri) ? CARD_TOOLS[uri] : null
  if (!card || typeof tool !== 'string' || !tool) return 'deny'
  if (CARD_NEVER_RELAYED.includes(tool) || tool.startsWith('privy_')) return 'deny'
  if (card.confirm.includes(tool)) return 'confirm'
  if (tool === card.tool || card.relay.includes(tool) || CARD_ALWAYS_RELAYED.includes(tool)) return 'relay'
  if (card.tool === 'show_error_card' && CARD_RETRYABLE_TOOLS.includes(tool) && structured && structured.retryTool === tool) {
    return 'relay'
  }
  return 'deny'
}

const CARD_SECRET_KEYS = new Set([
  'sessiontoken', 'embedtoken', 'accesstoken', 'refreshtoken', 'idtoken',
  'authtoken', 'authorization', 'bearer', 'apikey', 'secret', 'clientsecret',
  'credentials', 'mnemonic', 'seed', 'seedphrase', 'password', 'privatekey',
  'cookie',
])
const CARD_UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype'])

/** Drop credential-like keys at any depth (bare `token` is a coin symbol). */
function stripSecrets(value, depth = 0) {
  if (depth > 24) return null
  if (Array.isArray(value)) return value.map((item) => stripSecrets(item, depth + 1))
  if (!value || typeof value !== 'object') return value
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    if (CARD_UNSAFE_KEYS.has(key) || CARD_SECRET_KEYS.has(key.toLowerCase().replace(/[_-]/g, ''))) continue
    out[key] = stripSecrets(item, depth + 1)
  }
  return out
}

function clampCardHeight(height) {
  const value = Number(height)
  if (!Number.isFinite(value)) return CARD_HEIGHT_MIN
  return Math.min(CARD_HEIGHT_MAX, Math.max(CARD_HEIGHT_MIN, Math.ceil(value)))
}

/**
 * Fit a card to the pane. It lays out at the pane's width; once it reports
 * content wider than that, it keeps that wider layout (latched, so the frame
 * does not flip between widths) and is scaled down to the pane.
 */
function fitCard({ container, reported, latched }) {
  const width = Math.max(1, Math.floor(Number(container) || 0))
  let layout = Number(latched) || 0
  if (!layout && Number(reported) > width + 1) layout = Math.min(Math.ceil(Number(reported)), CARD_LAYOUT_MAX)
  if (!layout || layout <= width) return { layoutWidth: width, scale: 1, latched: null }
  return { layoutWidth: layout, scale: width / layout, latched: layout }
}

function isHttpsUrl(url) {
  if (typeof url !== 'string') return false
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

const rpcResult = (id, result) => ({ jsonrpc: '2.0', id, result })
const rpcError = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } })
const rpcNotification = (method, params) => ({ jsonrpc: '2.0', method, params })
const toolErrorResult = (text) => ({ isError: true, content: [{ type: 'text', text }] })

function cardHostContext({ theme, locale, width }) {
  return {
    theme: theme === 'dark' ? 'dark' : 'light',
    displayMode: 'inline',
    availableDisplayModes: ['inline'],
    platform: 'desktop',
    locale: locale || 'en-US',
    containerDimensions: { width: Math.floor(Number(width) || 0), maxHeight: CARD_HEIGHT_MAX },
  }
}

function cardInitializeResult(context) {
  return {
    protocolVersion: CARD_PROTOCOL_VERSION,
    hostInfo: { name: 'Hermes CoinFello plugin', version: '0.1.0' },
    hostCapabilities: { openLinks: {}, serverTools: {} },
    hostContext: cardHostContext(context),
  }
}

/** true while under `limit` calls in the last `windowMs`. */
function createRateLimiter(limit, windowMs, now = () => Date.now()) {
  const stamps = []
  return () => {
    const at = now()
    while (stamps.length && at - stamps[0] >= windowMs) stamps.shift()
    if (stamps.length >= limit) return false
    stamps.push(at)
    return true
  }
}

/**
 * The host side of one mounted card. `post` sends to the frame; `rest` is
 * ctx.rest; `confirm(preview)` resolves with the /execute response after the
 * human pressed Confirm, or null when they cancelled (the bridge itself never
 * calls /execute); `onSize` gets size-changed params; `context()` returns
 * { theme, locale, width }.
 */
function createCardBridge({ card, post, rest, confirm, openExternal, onSize, context, newId, limiter }) {
  const structured = (card.tool_result && card.tool_result.structuredContent) || {}
  const allow = limiter || createRateLimiter(CARD_CALLS_PER_MINUTE, 60000)
  const makeId = newId || (() => crypto.randomUUID())
  let disposed = false
  const send = (message) => {
    if (!disposed) post(message)
  }

  const relay = async (id, params) => {
    const name = params && typeof params.name === 'string' ? params.name : ''
    const raw = params && params.arguments
    const args = raw && typeof raw === 'object' && !Array.isArray(raw) ? stripSecrets(raw) : {}
    const decision = cardToolDecision(card.uri, name, structured)
    if (decision === 'deny') {
      send(rpcError(id, -32601, `${name || 'That tool'} is not available from this card in Hermes.`))
      return
    }
    if (!allow()) {
      send(rpcError(id, -32000, 'Too many requests from this card. Wait a minute.'))
      return
    }
    let response
    try {
      response = await rest(`/cards/${card.id}/call`, { method: 'POST', body: { tool: name, arguments: args } })
    } catch (exc) {
      send(rpcResult(id, toolErrorResult(String(exc))))
      return
    }
    if (!response || response.ok === false) {
      send(rpcResult(id, toolErrorResult((response && response.error) || 'Hermes could not complete that.')))
      return
    }
    if (decision !== 'confirm') {
      send(rpcResult(id, response.result || {}))
      return
    }
    if (!response.confirm) {
      send(rpcResult(id, toolErrorResult('Hermes could not prepare the confirmation. Nothing was sent.')))
      return
    }
    let executed = null
    try {
      executed = await confirm(response.confirm)
    } catch {
      executed = null
    }
    if (!executed) send(rpcResult(id, toolErrorResult(CARD_CANCELLED_TEXT)))
    else if (executed.ok === false) send(rpcResult(id, toolErrorResult(executed.error || 'Nothing was sent.')))
    else send(rpcResult(id, executed.result || {}))
  }

  const handle = (message) => {
    if (disposed || !message || typeof message !== 'object' || message.jsonrpc !== '2.0') return
    const { id, method, params } = message
    if (typeof method !== 'string') return // a response to our teardown: nothing waits on it
    if (id === undefined || id === null) {
      if (method === 'ui/notifications/initialized') {
        send(rpcNotification('ui/notifications/tool-input', card.tool_input || { arguments: {} }))
        send(rpcNotification('ui/notifications/tool-result', card.tool_result || {}))
      } else if (method === 'ui/notifications/size-changed') {
        onSize(params || {})
      }
      return
    }
    if (method === 'ui/initialize') send(rpcResult(id, cardInitializeResult(context())))
    else if (method === 'tools/call') relay(id, params)
    else if (method === 'ui/open-link') {
      const url = params && params.url
      if (isHttpsUrl(url)) {
        openExternal(url)
        send(rpcResult(id, {}))
      } else {
        send(rpcResult(id, toolErrorResult('Only https links open from a card.')))
      }
    } else if (method === 'ping') send(rpcResult(id, {}))
    else send(rpcError(id, -32601, `Hermes does not support ${method}.`))
  }

  return {
    handle,
    notifyContext: (partial) => send(rpcNotification('ui/notifications/host-context-changed', partial)),
    dispose: () => {
      send({ jsonrpc: '2.0', id: makeId(), method: 'ui/resource-teardown', params: {} })
      disposed = true
    },
  }
}
/* card-bridge:end */

const CARD_SHOWN_EVENT = 'plugin.coinfello.card.shown'

const currentTheme = () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')

function ConfirmSheet({ ctx, cardId, preview, onDone }) {
  const [busy, setBusy] = useState(false)
  const [expired, setExpired] = useState(!(preview.expires_in_seconds > 0))
  const isTrade = preview.tool === 'execute_intent'

  const confirmNow = async () => {
    setBusy(true)
    let response
    try {
      response = await ctx.rest(`/cards/${cardId}/execute`, {
        method: 'POST',
        body: { confirm_id: preview.confirm_id },
        timeoutMs: 180000,
      })
    } catch (exc) {
      response = {
        ok: false,
        error: isTrade
          ? `Hermes lost the answer (${String(exc)}). It may have gone through: check your CoinFello activity before trying again.`
          : String(exc),
      }
    }
    onDone(response || { ok: false, error: 'No response' })
  }

  return jsxs('section', {
    className: 'cf-card cf-confirm cf-stack',
    role: 'dialog',
    'aria-label': preview.title,
    children: [
      jsx('div', { className: 'cf-confirm-title', children: preview.title }),
      jsx('div', { children: preview.description }),
      (preview.rows || []).length
        ? jsx('div', {
            className: 'flex flex-col gap-1',
            children: preview.rows.map(([label, value], index) => jsx(Row, { label, value }, index)),
          })
        : null,
      isTrade
        ? jsx('div', {
            className: 'cf-hint',
            children: 'This runs from your automations wallet right away. Transactions cannot be reversed.',
          })
        : null,
      expired
        ? jsx('div', { className: 'cf-err', children: 'This confirmation expired. Ask the card for a fresh one.' })
        : jsxs('div', {
            className: 'cf-hint',
            children: ['Valid for ', jsx(Countdown, { seconds: preview.expires_in_seconds, onExpired: () => setExpired(true) })],
          }),
      jsxs('div', {
        className: 'flex gap-2',
        children: [
          jsx(Button, { size: 'sm', loading: busy, disabled: expired, onClick: confirmNow, children: isTrade ? 'Confirm' : 'Cancel automation' }),
          jsx(Button, { size: 'sm', variant: 'ghost', disabled: busy, onClick: () => onDone(null), children: isTrade ? 'Cancel' : 'Keep it' }),
        ],
      }),
    ],
  })
}

function CardFrame({ ctx, card }) {
  const queryClient = useQueryClient()
  const frameRef = useRef(null)
  const boxRef = useRef(null)
  const [height, setHeight] = useState(240)
  const [reported, setReported] = useState(0)
  const [latched, setLatched] = useState(null)
  const [container, setContainer] = useState(0)
  const [confirmation, setConfirmation] = useState(null)

  // The pane can be resized: re-fit from scratch when its width changes
  // (not when the card's own height does).
  useEffect(() => {
    const box = boxRef.current
    if (!box) return undefined
    let width = -1
    const update = () => {
      if (box.clientWidth === width) return
      width = box.clientWidth
      setContainer(width)
      setLatched(null)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  const fit = fitCard({ container, reported, latched })
  useEffect(() => {
    if (fit.latched !== latched) setLatched(fit.latched)
  }, [fit.latched, latched])

  useEffect(() => {
    const post = (message) => {
      const frame = frameRef.current
      // A sandboxed (opaque-origin) frame can only be addressed with '*'.
      if (frame && frame.contentWindow) frame.contentWindow.postMessage(message, '*')
    }
    const bridge = createCardBridge({
      card,
      post,
      rest: (path, options) => ctx.rest(path, options),
      confirm: (preview) => new Promise((resolve) => setConfirmation({ preview, resolve })),
      openExternal: (url) => ctx.os.openExternal(url),
      onSize: (params) => {
        if (Number(params.height) > 0) setHeight(clampCardHeight(params.height))
        if (Number(params.width) > 0) setReported(Number(params.width))
      },
      context: () => ({
        theme: currentTheme(),
        locale: navigator.language,
        width: boxRef.current ? boxRef.current.clientWidth : 0,
      }),
    })
    const onMessage = (event) => {
      const frame = frameRef.current
      // Only this card's own frame speaks to this bridge.
      if (!frame || event.source !== frame.contentWindow) return
      bridge.handle(event.data)
    }
    window.addEventListener('message', onMessage)
    let theme = currentTheme()
    const observer = new MutationObserver(() => {
      const next = currentTheme()
      if (next !== theme) {
        theme = next
        bridge.notifyContext({ theme: next })
      }
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => {
      window.removeEventListener('message', onMessage)
      observer.disconnect()
      bridge.dispose()
      setConfirmation((open) => {
        if (open) open.resolve(null)
        return null
      })
    }
  }, [card.id, ctx])

  const finish = (response) => {
    if (!confirmation) return
    confirmation.resolve(response)
    setConfirmation(null)
    if (response && response.ok !== false) queryClient.invalidateQueries({ queryKey: ['coinfello', 'portfolio'] })
  }

  return jsxs('div', {
    className: 'cf-stack',
    children: [
      confirmation ? jsx(ConfirmSheet, { ctx, cardId: card.id, preview: confirmation.preview, onDone: finish }) : null,
      jsx('div', {
        ref: boxRef,
        className: 'cf-card-box',
        style: { height: Math.ceil(height * fit.scale) },
        children: container
          ? jsx(SandboxedFrame, {
              ref: frameRef,
              src: card.src,
              title: `CoinFello ${card.title || 'card'}`,
              sandbox: 'allow-scripts',
              style: {
                display: 'block',
                border: 0,
                width: fit.layoutWidth,
                height,
                transform: fit.scale === 1 ? undefined : `scale(${fit.scale})`,
                transformOrigin: 'top left',
              },
            })
          : null,
      }),
    ],
  })
}

function CardSlot({ ctx, summary, onDismiss }) {
  // Outside the ['coinfello'] prefix: the pane's own refreshes must not
  // reload a mounted card.
  const cardDoc = useQuery({
    queryKey: ['coinfello-card', summary.id],
    queryFn: () => ctx.rest(`/cards/${summary.id}?theme=${currentTheme()}`),
    staleTime: Infinity,
  })
  const data = cardDoc.data
  let content
  if (!data) content = jsx('div', { className: 'cf-skeleton', role: 'status', 'aria-label': 'Loading card', style: { height: 120 } })
  else if (data.ok === false) content = jsx('div', { className: 'cf-card cf-hint', children: errorOf(data, 'Could not load this card.') })
  else content = jsx(CardFrame, { ctx, card: data })
  return jsxs('div', {
    className: 'cf-section',
    children: [
      jsxs('div', {
        className: 'cf-card-head',
        children: [
          jsx('span', { className: 'cf-card-title', title: summary.title || undefined, children: summary.title || 'Card' }),
          jsx('button', {
            type: 'button',
            className: 'cf-icon-btn',
            'aria-label': 'Close card',
            title: 'Close card',
            onClick: () => onDismiss(summary.id),
            children: jsx(Codicon, { name: 'close', size: 14 }),
          }),
        ],
      }),
      content,
    ],
  })
}

function Cards({ ctx }) {
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['coinfello', 'cards'],
    queryFn: () => ctx.rest('/cards'),
    // The event is instant; this catches Hermes builds without it.
    refetchInterval: 20 * 1000,
  })
  useEffect(() => {
    if (typeof ctx.onEvent !== 'function') return undefined
    return ctx.onEvent(CARD_SHOWN_EVENT, () => queryClient.invalidateQueries({ queryKey: ['coinfello', 'cards'] }))
  }, [ctx, queryClient])

  const dismiss = async (id) => {
    await ctx.rest(`/cards/${id}/dismiss`, { method: 'POST', body: {} })
    queryClient.invalidateQueries({ queryKey: ['coinfello', 'cards'] })
  }

  const items = (list.data && list.data.ok !== false && list.data.cards) || []
  if (items.length === 0) return null
  return jsx('div', {
    className: 'cf-stack',
    style: { gap: 14 },
    children: items.slice(0, 3).map((card) => jsx(CardSlot, { ctx, summary: card, onDismiss: dismiss }, card.id)),
  })
}

// -- pane ----------------------------------------------------------------------

function Pane({ ctx }) {
  const queryClient = useQueryClient()
  const status = useQuery({
    queryKey: ['coinfello', 'status'],
    queryFn: () => ctx.rest('/status'),
    refetchInterval: 30 * 1000,
  })
  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: ['coinfello'] }), [queryClient])
  const data = status.data
  const connected = !!(data && data.connected)
  const [view, setView] = useState({ kind: 'home' })
  const [allowanceMessage, setAllowanceMessage] = useState('')
  // A presentation preference for this app: plugin-scoped local storage.
  const [brand, setBrandState] = useState(() => ctx.storage.get('brandColors', false) === true)
  const setBrand = (on) => {
    setBrandState(on)
    ctx.storage.set('brandColors', on)
  }
  const [homeTab, setHomeTabState] = useState(() => (ctx.storage.get('homeTab', 'assets') === 'activity' ? 'activity' : 'assets'))
  const setHomeTab = (tab) => {
    setHomeTabState(tab)
    ctx.storage.set('homeTab', tab)
  }
  const home = () => setView({ kind: 'home' })

  useLimitPoll(ctx, connected ? data.pending_limit_change_url : null, refresh, setAllowanceMessage)

  useEarnRequests(ctx, connected && !!data.earn_supported, (request) =>
    setView({ kind: 'earn', query: request.query || '', requestId: request.id }),
  )

  const signOut = async () => {
    // Optimistic: show the signed-out pane now. The backend forgets the
    // session at once and revokes it server-side in the background.
    const previous = queryClient.getQueryData(['coinfello', 'status']) || {}
    await queryClient.cancelQueries({ queryKey: ['coinfello'] })
    queryClient.removeQueries({ queryKey: ['coinfello', 'portfolio'] })
    queryClient.removeQueries({ queryKey: ['coinfello', 'wallet'] })
    queryClient.removeQueries({ queryKey: ['coinfello', 'activity'] })
    queryClient.setQueryData(['coinfello', 'status'], {
      endpoint: previous.endpoint,
      app_url: previous.app_url,
      email: previous.email,
      sign_in_mode: previous.sign_in_mode,
      connected: false,
    })
    setView({ kind: 'home' })
    setAllowanceMessage('')
    closeEmbedTabs()
    try {
      await ctx.rest('/disconnect', { method: 'POST', body: {} })
    } finally {
      refresh()
    }
  }

  let body
  if (!data) {
    body = jsxs('div', {
      className: 'cf-card',
      children: [
        jsx('div', { className: 'cf-skeleton', style: { width: 110, height: 12 } }),
        jsx('div', { className: 'cf-skeleton', style: { width: 160, height: 30, marginTop: 14 } }),
      ],
    })
  } else if (connected && view.kind === 'send') {
    body = jsx(SendFlow, { ctx, portfolio: view.portfolio, onClose: home })
  } else if (connected && view.kind === 'swap') {
    body = jsx(EmbedView, { ctx, appUrl: data.app_url, kind: 'swap', onClose: home })
  } else if (connected && view.kind === 'earn') {
    body = jsx(EmbedView, {
      key: view.requestId || 'earn',
      ctx,
      appUrl: data.app_url,
      kind: 'earn',
      query: view.query || '',
      onClose: home,
    })
  } else if (connected && view.kind === 'settings') {
    body = jsx(Settings, { ctx, status: data, refresh, onBack: home, onSignOut: signOut, message: allowanceMessage, setMessage: setAllowanceMessage, brand, setBrand })
  } else if (connected) {
    body = jsxs(Fragment, {
      children: [
        jsx(Cards, { ctx }),
        jsx(Hero, {
          ctx,
          onSend: (portfolio) => setView({ kind: 'send', portfolio }),
          onSwap: () => setView({ kind: 'swap' }),
          onEarn: () => setView({ kind: 'earn' }),
        }),
        jsx(AllowanceNotice, { status: data, message: allowanceMessage, onOpen: () => setView({ kind: 'settings' }) }),
        jsx(Assets, { ctx, tab: homeTab, setTab: setHomeTab }),
      ],
    })
  } else body = jsx(HermesSignIn, { ctx, status: data, refresh })

  const readOnly = connected && data.access && data.access !== 'unknown' && data.access !== 'trade'
  const settingsOpen = view.kind === 'settings'
  return jsxs('div', {
    className: cn('cf', brand && 'is-brand'),
    children: [
      jsxs('header', {
        className: 'cf-header',
        children: [
          jsx(Logo, {}),
          jsxs('div', {
            className: 'cf-header-end',
            children: [
              jsxs('span', {
                className: 'cf-status',
                children: [
                  jsx('span', { className: cn('cf-dot', connected && (readOnly ? 'is-warn' : 'is-on')) }),
                  !data ? 'Checking…' : connected ? (readOnly ? 'Read-only' : 'Connected') : 'Not signed in',
                ],
              }),
              connected
                ? jsx('button', {
                    type: 'button',
                    className: 'cf-icon-btn',
                    'aria-label': settingsOpen ? 'Close settings' : 'Settings',
                    'aria-pressed': settingsOpen,
                    title: settingsOpen ? 'Close settings' : 'Settings',
                    onClick: () => setView(settingsOpen ? { kind: 'home' } : { kind: 'settings' }),
                    children: jsx(Codicon, { name: settingsOpen ? 'close' : 'settings-gear', size: 16 }),
                  })
                : null,
            ],
          }),
        ],
      }),
      body,
    ],
  })
}

function Chip({ ctx }) {
  const status = useQuery({
    queryKey: ['coinfello', 'status'],
    queryFn: () => ctx.rest('/status'),
    refetchInterval: 30 * 1000,
  })
  const connected = !!(status.data && status.data.connected)
  return jsxs('div', {
    className: cn('inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem]', muted),
    children: [jsx(StatusDot, { tone: connected ? 'good' : 'muted' }), 'coinfello'],
  })
}

export default {
  id: ID,
  name: 'CoinFello',
  register(ctx) {
    installStyles(ctx)
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'coinfello',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(Pane, { ctx }),
    })
    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 140,
      render: () => jsx(Chip, { ctx }),
    })
  },
}
