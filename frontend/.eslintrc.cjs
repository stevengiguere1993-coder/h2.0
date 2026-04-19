/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,
  extends: ["next/core-web-vitals", "next/typescript"],
  rules: {
    // These are style-only warnings; we do not want them to fail a
    // production build. Re-enable case by case once content is stable.
    "react/no-unescaped-entities": "off",
    "@typescript-eslint/prefer-as-const": "off",
    "@typescript-eslint/no-unused-vars": "off",
    "@typescript-eslint/no-explicit-any": "off",
    "@typescript-eslint/no-empty-object-type": "off",
    "@next/next/no-img-element": "off"
  }
};
