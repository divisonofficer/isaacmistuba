"""Full intended camera coverage before any gallery/inspection registry mutation."""

def validate_frame_coverage(views, receipt, review, required_names=None):
    expected = [v['name'] for v in views]
    if required_names is not None and not set(required_names).issubset(expected):
        raise ValueError(f'Intended manifest omits full-scene required views: {sorted(set(required_names)-set(expected))}')
    actual = [f['name'] for f in receipt['frames']]
    reviewed = list(review['frames_reviewed'])
    for label, names in [('view manifest', expected), ('render receipt', actual), ('visual review', reviewed)]:
        if len(names) != len(set(names)):
            raise ValueError(f'Duplicate camera names in {label}')
    if set(actual) != set(expected):
        raise ValueError(f'Render coverage mismatch: missing={sorted(set(expected)-set(actual))}, unexpected={sorted(set(actual)-set(expected))}')
    if set(reviewed) != set(expected):
        raise ValueError('Visual review does not cover the full intended view manifest')
    by_name = {v['name']: v for v in views}
    for frame in receipt['frames']:
        view = by_name[frame['name']]
        camera = frame.get('camera', {})
        for key in ['name', 'location', 'target', 'hfov', 'ortho_scale']:
            if key in view and camera.get(key) != view[key]:
                raise ValueError(f'Camera mismatch for {frame["name"]}: {key}')
        for key, frame_key in [('render_width', 'width'), ('samples', 'samples')]:
            if key in view and frame.get(frame_key) != view[key]:
                raise ValueError(f'Render setting mismatch for {frame["name"]}: {key}')
    return len(expected)
