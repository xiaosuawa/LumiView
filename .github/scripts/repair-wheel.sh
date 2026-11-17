#!/usr/bin/env bash
# Repair the Linux wheel with auditwheel.
#
# GTK/GLib libraries can never be bundled into the wheel: the GObject type
# registry is process-global, so a second copy breaks any process that also
# links the system GTK (LumiView's own tao window and wryview both do).
# libdbus-1/libsystemd likewise exist on every desktop that can run GTK3
# (the gtk .deb depends on them) — bundling them only adds weight and risks
# version skew.
set -euo pipefail

excludes=(
  'libgtk-3.*'
  'libgdk-3.*'
  'libglib-2.0.*'
  'libgobject-2.0.*'
  'libgio-2.0.*'
  'libgmodule-2.0.*'
  'libgdk_pixbuf-2.0.*'
  'libpango-1.0.*'
  'libpangocairo-1.0.*'
  'libpangoft2-1.0.*'
  'libatk-1.0.*'
  'libharfbuzz.*'
  'libfribidi.*'
  'libepoxy.*'
  'libcairo.*'
  'libcairo-gobject.*'
  'libxkbcommon.*'
  'libwayland-client.*'
  'libdbus-1.*'
  'libsystemd.*'
  'libgcrypt.*'
  'libgpg-error.*'
  'libcap.*'
  'libzstd.*'
  'liblz4.*'
  'liblzma.*'
)

args=()
for pattern in "${excludes[@]}"; do
  args+=(--exclude "$pattern")
done

shopt -s nullglob
wheels=(dist/*.whl)
if ((${#wheels[@]} == 0)); then
  echo "no wheel found in dist/" >&2
  exit 1
fi

for wheel in "${wheels[@]}"; do
  auditwheel repair "${args[@]}" -w dist "$wheel"
done

# Drop the un-repaired linux_x86_64/linux_aarch64 wheels; only the manylinux
# ones are uploadable to PyPI.
rm -f dist/*-linux_*.whl
