/** @type {import("stylelint").Config} */
export default {
  extends: ["stylelint-config-standard", "stylelint-config-css-modules"],
  rules: {
    // CSS Modules 在 TS 中以 styles.xxx 访问，类名统一 camelCase。
    "selector-class-pattern": [
      "^[a-z][a-zA-Z0-9]*$",
      { message: (selector) => `类名应为 camelCase：${selector}` }
    ],
    // 颜色只能来自设计变量，保证换肤只改 tokens.css 一处。
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": [
      "rgb",
      "rgba",
      "hsl",
      "hsla",
      "hwb",
      "lab",
      "lch",
      "oklab",
      "oklch",
      "color"
    ]
  },
  overrides: [
    {
      files: ["src/styles/tokens.css"],
      rules: { "color-no-hex": null, "color-named": null }
    }
  ]
};
