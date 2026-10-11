// Shared esbuild plugin for tests that bundle web/ modules for rendering.
// The terrain and MapLibre modules are dynamic imports that rendering never reaches, so they stay external.
// Vite `?url` asset imports (stylesheets, fonts) bundle as their path, standing in for Vite's hashed URL.
export const rendererPlugin = {name: 'renderers', setup: b => {
  b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}));
  b.onResolve({filter: /\?url$/}, args => ({path: args.path, namespace: 'url'}));
  b.onLoad({filter: /.*/, namespace: 'url'}, args => ({contents: `export default ${JSON.stringify(args.path)};`, loader: 'js'}));
}};
export const rendererPlugins = [rendererPlugin];
