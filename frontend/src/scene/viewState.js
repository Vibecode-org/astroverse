/** Show exactly one scale's group and light it for that scale.
 *
 * The three scales are mutually exclusive, so this is the single place that
 * decides what is on screen. Every caller mutates the same shared scene state
 * object, so this must stay a pure read/write of that object.
 */
export function applyViewState(s, nextView) {
  if (!s.scene) return;
  s.view = nextView;
  s.system.visible = nextView === 'solar';
  s.nearby.visible = nextView === 'local';
  s.galaxy.group.visible = nextView === 'galaxy';
  s.galaxyMarkers.visible = nextView === 'galaxy';
  if (s.sunLight) {
    s.sunLight.visible = nextView === 'solar';
    // ambient держит «окрестности» и галактику читаемыми: там нет источника
    // на сцене, и без него все тела выходят чёрными силуэтами.
    s.ambient.intensity = nextView === 'solar' ? 0.07 : nextView === 'local' ? 0.5 : 0.7;
  }
}
