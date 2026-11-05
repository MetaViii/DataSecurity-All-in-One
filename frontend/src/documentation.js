// Only bundled guides may navigate inside the documentation dialog.
const bundled = {
  'code-tour.md': 'code-tour',
  'workbench-guide.md': 'workbench',
  'ctf-recipes.md': 'recipes',
  'real-ctf.md': 'real-ctf',
  'contest-round2.md': 'contest-round2',
  'correction.md': 'correction',
  'node-catalog.md': 'nodes',
  'advanced-nodes.md': 'advanced-nodes',
  'architecture.md': 'architecture',
  'plugin-development.md': 'plugins',
  'plugin-manager.md': 'plugin-manager',
};
export const documentTarget = (href) => {
  const path = href.replace(/^\.\//, '').split('#')[0];
  return Object.hasOwn(bundled, path) ? bundled[path] : null;
};
