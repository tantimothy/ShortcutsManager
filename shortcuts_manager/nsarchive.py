"""Minimal NSKeyedArchiver unarchiver.

Core Data "transformable" attributes (and plenty of other Apple blobs) are
stored as a plist shaped like:

    {"$archiver": "NSKeyedArchiver", "$version": 100000,
     "$top": {"root": UID(1)}, "$objects": [...]}

Objects reference each other by index into "$objects" via plistlib.UID.
This walks that graph and returns plain dicts/lists/scalars, with the
original Objective-C class name kept under "$class" for dict-shaped
objects so you can still tell what you're looking at.

It is not a full NSKeyedArchiver implementation (no custom
NSCoding-aware reconstruction of e.g. NSData subclasses) -- it's just
enough to make an opaque blob readable.
"""

import plistlib


def loads(data):
    try:
        top = plistlib.loads(data, fmt=plistlib.FMT_BINARY)
    except Exception:
        return None
    if not isinstance(top, dict) or top.get("$archiver") != "NSKeyedArchiver":
        return None
    objects = top.get("$objects", [])
    memo = {}
    resolved = _resolve(top.get("$top", {}), objects, memo)
    if isinstance(resolved, dict) and len(resolved) == 1 and "root" in resolved:
        return resolved["root"]
    return resolved


def _resolve(obj, objects, memo):
    if isinstance(obj, plistlib.UID):
        idx = obj.data
        if idx in memo:
            return memo[idx]
        if idx >= len(objects):
            return None
        raw = objects[idx]
        if raw == "$null":
            return None
        placeholder = {}
        memo[idx] = placeholder
        result = _resolve_object(raw, objects, memo)
        if isinstance(result, dict):
            placeholder.update(result)
            return placeholder
        memo[idx] = result
        return result
    if isinstance(obj, dict):
        return {k: _resolve(v, objects, memo) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, objects, memo) for v in obj]
    return obj


def _resolve_object(raw, objects, memo):
    if not isinstance(raw, dict):
        return _resolve(raw, objects, memo)

    class_info = raw.get("$class")
    classname = None
    if isinstance(class_info, plistlib.UID):
        resolved_class = objects[class_info.data] if class_info.data < len(objects) else None
        if isinstance(resolved_class, dict):
            classname = resolved_class.get("$classname")

    # NSArray / NSSet / NSOrderedSet
    if "NS.objects" in raw:
        return [_resolve(v, objects, memo) for v in raw["NS.objects"]]

    # NSDictionary: parallel NS.keys / NS.objects arrays
    if "NS.keys" in raw and "NS.objects" in raw:
        keys = [_resolve(v, objects, memo) for v in raw["NS.keys"]]
        values = [_resolve(v, objects, memo) for v in raw["NS.objects"]]
        return dict(zip(keys, values))

    # NSString / NSMutableString
    if "NS.string" in raw:
        return raw["NS.string"]

    # NSData / NSMutableData
    if "NS.data" in raw:
        return raw["NS.data"]

    out = {"$class": classname} if classname else {}
    for k, v in raw.items():
        if k in ("$class",):
            continue
        out[k] = _resolve(v, objects, memo)
    return out
