# Control Plane Geometry Endpoint

The control plane exposes scene OBJ geometry for the future 3D viewport through:

```text
GET /api/scenes/{scene_id}/geometry/{mesh_id}.obj
```

Use `encodeURIComponent` for both `scene_id` and `mesh_id`. The web UI helper is:

```ts
sceneGeometryUrl(sceneId, meshId)
```

The daemon resolves `mesh_id` against the scene snapshot in this order:

- `mesh.mesh_id`
- `mesh.source_path`
- `mesh.name`
- `Path(mesh.geometry_path).stem`

Successful responses stream the OBJ file using the existing repository artifact serving path. Error responses are JSON with an `error` field for unknown scenes, missing snapshots, or missing geometry.

This endpoint is intended for Phase E `Viewport3D` / `OBJLoader` integration and is separate from the Phase C primitive component work.
