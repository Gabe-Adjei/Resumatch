// React + htm bindings, in one place.
//
// React and htm arrive as UMD globals from the CDN (see app.html) rather than
// through a bundler. That is a deliberate trade: the app stays a single
// shareable link with no build step, which matters more for this project than
// a module graph would.
//
// `htm` gives JSX-style tagged templates without a transpiler. Two gotchas
// worth knowing, because neither fails loudly:
//   - component tags interpolate the function: html`<${Foo} x=${1} />`
//   - a closing tag for a component is html`<//>`

const React = window.React;

export const html = window.htm.bind(React.createElement);

export const {
  useState,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useCallback,
} = React;

export default React;
