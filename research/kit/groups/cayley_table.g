# Export the Cayley table of GAP's SmallGroup(n, i) as JSON for
# research/kit/group_algebra.small_group: elements in GAP's Elements(G) order
# with the identity first, table[r][c] = index of g_r * g_c.
#
#   echo 'Read("research/kit/groups/cayley_table.g"); WriteCayleyTable(64, 61, "research/kit/groups/smallgroup_64_61.json"); QUIT;' | gap -q -b
#
# The committed tables were written by GAP 4.15.1 with smallgrp 1.5.4; both
# versions are recorded in each file.
WriteCayleyTable := function(n, i, path)
  local G, el, N, s, r, c;
  G := SmallGroup(n, i);
  el := Elements(G);
  N := Length(el);
  s := OutputTextFile(path, false);
  SetPrintFormattingStatus(s, false);
  AppendTo(s, "{\"order\": ", n, ", \"gap_id\": ", i,
    ", \"structure_description\": \"", StructureDescription(G), "\"",
    ", \"gap_version\": \"", GAPInfo.Version, "\"",
    ", \"smallgrp_version\": \"", GAPInfo.PackagesInfo.smallgrp[1].Version, "\"",
    ",\n \"ordering\": \"GAP Elements(G), identity first\", \"convention\": \"table[r][c] is the index of g_r * g_c\"",
    ",\n \"elements\": [");
  for r in [1..N] do
    AppendTo(s, "\"", String(el[r]), "\"");
    if r < N then AppendTo(s, ", "); fi;
  od;
  AppendTo(s, "],\n \"table\": [\n");
  for r in [1..N] do
    AppendTo(s, "  [");
    for c in [1..N] do
      AppendTo(s, Position(el, el[r] * el[c]) - 1);
      if c < N then AppendTo(s, ","); fi;
    od;
    AppendTo(s, "]");
    if r < N then AppendTo(s, ",\n"); else AppendTo(s, "\n"); fi;
  od;
  AppendTo(s, " ]}\n");
  CloseStream(s);
end;
