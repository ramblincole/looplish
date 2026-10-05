/** @type {import("stylelint").Config} */
export default {
  extends: ["stylelint-config-standard", "stylelint-config-css-modules"],
  // 旧的全局样式表在 PR 3 删除，迁移完成前不纳入检查。
  ignoreFiles: ["src/styles.css"],
  rules: {
    // CSS Modules 在 TS 中以 styles.xxx 访问，类名统一 camelCase。
    "selector-class-pattern": [
      "^[a-z][a-zA-Z0-9]*$",
      { message: (selector) => `类名应为 camelCase：${selector}` }
    ],
    // 颜色只能来自设计变量，保证换肤只改 tokens.css 一处。
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla"]
  },
  overrides: [
    {
      files: ["src/styles/tokens.css"],
      rules: { "color-no-hex": null, "color-named": null }
    }
  ]
};
