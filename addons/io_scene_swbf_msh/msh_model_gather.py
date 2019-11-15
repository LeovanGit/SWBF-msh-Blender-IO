""" Gathers the Blender objects from the current scene and returns them as a list of
    Model objects. """

import bpy
from typing import List, Set, Dict, Tuple
from itertools import zip_longest
from .msh_model import *
from .msh_model_utilities import *
from .msh_utilities import *

SKIPPED_OBJECT_TYPES = {"LATTICE", "CAMERA", "LIGHT", "SPEAKER", "LIGHT_PROBE"}
MESH_OBJECT_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "GPENCIL"}

def gather_models() -> List[Model]:
    """ Gathers the Blender objects from the current scene and returns them as a list of
        Model objects. """

    depsgraph = bpy.context.evaluated_depsgraph_get()
    parents = create_parents_set()

    models_list: List[Model] = []

    for uneval_obj in bpy.context.scene.objects:
        if uneval_obj.type in SKIPPED_OBJECT_TYPES and uneval_obj.name not in parents:
            continue

        obj = uneval_obj.evaluated_get(depsgraph)

        model = Model()
        model.name = obj.name
        model.model_type = get_model_type(obj)
        model.hidden = get_is_model_hidden(obj)
        model.transform.rotation = obj.rotation_quaternion @ obj.delta_rotation_quaternion
        model.transform.translation = add_vec(obj.location, obj.delta_location)

        if obj.parent is not None:
            model.parent = obj.parent.name

        if obj.type in MESH_OBJECT_TYPES:
            mesh = obj.to_mesh()
            model.geometry = create_mesh_geometry(mesh)
            obj.to_mesh_clear()

            mesh_scale = get_object_worldspace_scale(obj)
            scale_segments(mesh_scale, model.geometry)

        models_list.append(model)

    return models_list

def create_parents_set() -> Set[str]:
    """ Creates a set with the names of the Blender objects from the current scene
        that have at least one child. """
        
    parents = set()

    for obj in bpy.context.scene.objects:
        if obj.parent is not None:
            parents.add(obj.parent.name)

    return parents

def create_mesh_geometry(mesh: bpy.types.Mesh) -> List[GeometrySegment]:
    """ Creates a list of GeometrySegment objects from a Blender mesh.
        Does NOT create triangle strips in the GeometrySegment however. """

    if mesh.has_custom_normals:
        mesh.calc_normals_split()

    mesh.validate_material_indices()
    mesh.calc_loop_triangles()

    material_count = max(len(mesh.materials), 1)

    segments: List[GeometrySegment] = [GeometrySegment() for i in range(material_count)]
    vertex_remap: List[Dict[Tuple(int, int), int]] = [dict() for i in range(material_count)]
    polygons: List[Set[int]] = [set() for i in range(material_count)]

    if mesh.vertex_colors.active is not None:
        for segment in segments:
            segment.colors = []

    for segment, material in zip(segments, mesh.materials):
        segment.material_name = material.name

    def add_vertex(material_index: int, vertex_index: int, loop_index: int) -> int:
        nonlocal segments, vertex_remap

        segment = segments[material_index]
        remap = vertex_remap[material_index]

        if (vertex_index, loop_index) in remap:
            return remap[(vertex_index, loop_index)]

        new_index: int = len(segment.positions)
        remap[(vertex_index, loop_index)] = new_index

        segment.positions.append(mesh.vertices[vertex_index].co.copy())

        if mesh.has_custom_normals:
            segment.normals.append(mesh.loops[loop_index].normal.copy())
        else:
            segment.normals.append(mesh.vertices[vertex_index].normal.copy())

        if mesh.uv_layers.active is None:
            segment.texcoords.append(Vector((0.0, 0.0)))
        else:
            segment.texcoords.append(mesh.uv_layers.active.data[loop_index].uv.copy())

        if segment.colors is not None:
            segment.colors.append([v for v in mesh.vertex_colors.active.data[loop_index].color])

        return new_index

    for tri in mesh.loop_triangles:
        polygons[tri.material_index].add(tri.polygon_index)
        segments[tri.material_index].triangles.append(
            [add_vertex(tri.material_index, v, l) for v, l in zip(tri.vertices, tri.loops)])

    for segment, remap, polys in zip(segments, vertex_remap, polygons):
        for poly_index in polys:
            poly = mesh.polygons[poly_index]

            segment.polygons.append([remap[(v, l)] for v, l in zip(poly.vertices, poly.loop_indices)])

    return segments

def get_object_worldspace_scale(obj: bpy.types.Object) -> Vector:
    """ Get the worldspace scale transform for a Blender object. """

    scale = mul_vec(obj.scale, obj.delta_scale)

    while obj.parent is not None:
        obj = obj.parent
        scale = mul_vec(scale, mul_vec(obj.scale, obj.delta_scale))

    return scale

def get_model_type(obj: bpy.types.Object) -> ModelType:
    """ Get the ModelType for a Blender object. """
    # TODO: Skinning support, etc

    if obj.type in MESH_OBJECT_TYPES:
        return ModelType.STATIC

    return ModelType.NULL

def get_is_model_hidden(obj: bpy.types.Object) -> bool:
    """ Gets if a Blender object should be marked as hidden in the .msh file. """

    name = obj.name.lower()

    if name.startswith("sv_"):
        return True
    if name.startswith("p_"):
        return True
    if name.startswith("collision"):
        return True
    if obj.type not in MESH_OBJECT_TYPES:
        return True

    return False
