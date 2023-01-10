# noinspection PyUnresolvedReferences
r"""Functions assigning errors to the magnets and monitors of a lattice,
enabling the errors and computing linear optics of the lattice with errors.

The processing of errors in PyAT is done in two steps:

#. The definition of errors: errors are stored in dedicated attributes of the
   lattice elements by :py:func:`assign_errors`. Random errors are generated,
   cumulated with systematic errors and stored in dedicated attributes.
   Nothing changes in tracking at this stage because the error attributes are
   ignored,
#. The activation of errors by :py:func:`enable_errors`: errors are moved into
   the standard element attributes of a new :py:class:`.Lattice`.

All error definitions may be given to the :py:func:`assign_errors` in 2
possible forms:

* **a tuple of values**: (*systematic*, *random*). The *systematic* value
  is applied unchanged to all the selected elements, the *random* value is
  taken as the standard deviation of the generated error distribution,
* **a single value**: it acts as the *random* part of the previous form,
  and there is no systematic error.

.. _monitor-errors:

Monitor errors
==============

The following errors are applied in that order:

BPMOffset:
    *[offset_x, offset_y]* array [m], all errors, electrical or mechanical,
    acting as if the monitor was shifted from the reference axis.
BPMTilt:
    *tilt* [rd], all errors, electrical or mechanical, acting as if the monitor
    was rotated around the z axis.
BPMGain:
    *[gain_x, gain_y]* array giving the magnification introduced by the monitor

This results in the following computation:

.. math::

    \begin{pmatrix} x_{monitor} \\ y_{monitor} \end{pmatrix} =
    \begin{pmatrix} g_x & 0 \\ 0 & g_y \end{pmatrix}
    \begin{pmatrix} cos\theta & sin\theta \\
    -sin\theta & cos\theta \end{pmatrix}
    \left[
    \begin{pmatrix} x_{beam} \\ y_{beam} \end{pmatrix} -
    \begin{pmatrix} o_x \\ o_y \end{pmatrix}
    \right]

.. note::
    Monitor errors may be applied to any element: when enabling errors, the
    beam position reported at the element location, whatever it is, will be
    affected by these attributes.

.. _magnet-alignment-errors:

Magnet alignment errors
=======================

ShiftErr:
    *[shift_x, shift_y]* array [m], magnet shift from the
    reference axis
RotationErr:
    *tilt* or *[tilt, pitch, yaw]* rotation around the z, x, y axis

.. _magnet-field-errors:

Magnet field errors
===================

PolynomBErr:
    Absolute field error. *PolynomAErr* is added to the magnet's *PolynomB*
PolynomAErr:
    Absolute field error. *PolynomBErr* is added to the magnet's *PolynomA*
ScalingPolynomBErr:
    Relative field error. *ScalingPolynomBErr* is the multipolar field error
    relative to the main magnet field component. When
    :py:func:`enabling the errors<enable_errors>`, *ScalingPolynomBErr* is
    multiplied by the magnet strengh and added to *PolynomB*
ScalingPolynomAErr:
    Relative field error. *ScalingPolynomAErr* is the skew multipolar field
    error relative to the main magnet field component.

.. admonition:: Example of use

    Let's imagine a standard quadrupole and see how error attributes can be
    related to the results of magnetic measurements:

    Systematic errors:
        The magnetic measurements at the nominal current give systematic
        octupole and 12-pole components in addition to the quadrupole.
        *PolynomB* looks like *[0, B2, 0, B4, 0, B6]*\ . The 1st step is to
        normalise with respect to the quadrupole component:

        *[0, 1, 0, B4/B2, 0, B6/B2]*

        The 1 goes to the main field, the rest goes to errors:

        >>> qp.PolynomB = [0, B2]
        >>> qp.ScalingPolynomBErr = (0, [0, 0, 0, B4/B2, 0, B6/B2])

        Note that the systematic error component must be in the 2nd position in
        the error tuple.

        Now assume that after tuning we set the quadrupole to C2 instead B2:

        >>> qp.PolynomB = [0, C2]

        :py:func:`enable_errors` will compute:

        *[0, C2] + C2*[0, 0, 0, B4/B2, 0, B6/B2] =
        [0, C2, 0, C2/B2*B4, 0, C2/B2*B6]*

        which is the exact scaling of the measured field by a ratio C2/B2.

    Random errors:
        In addition, we know that we have a random relative field integral error
        of 10\ :sup:`-3` and a random sextupole B3.  All this also scales with
        the magnet current, so we add a random component:

        >>> qp.ScalingPolynomBErr = ([0, 1.E-3, B3/B2, 1.E-3/B2, 0, 1.E-3/B2],
        ...                          [0, 0, 0, B4/B2, 0, B6/B2])

        After generating random numbers and multiplying by B2, we get the
        correct random contribution.

        Remark: in this example, if the field integral error results from
        mechanical magnet length, the random contributions to B2,
        B4 and B6 should be correlated, while the one of B3 is uncorrelated.
        Here a random value is generated for each component, so there is no
        correlation.

    Case of an arbitrary multipole magnet:
        Now let's consider a combined-function magnet, let's say a
        quadrupole-sextupole:

        >>> qp.PolynomB = [0, B2, B3]

        For errors, we can arbitrarily decide it's a :py:class:`.Quadrupole`
        and normalise the errors with B2:

        >>> qp.ScalingPolynomBErr = (0, [0, 0, 0, B4/B2, 0, B6/B2])

        which will then be multiplied by C2, strength of the quadrupole.

        or decide it's a :py:class:`.Sextupole` and normalise the errors with B3

        >>> qp.ScalingPolynomBErr = (0, [0, 0, 0, B4/B3, 0, B6/B3])

        which will be multiplied by C3, strength of the sextupole.

        Both choices are equivalent: the result will be **exactly the same**
        (provided the user correctly scales the main field *[0, C2, C3]*\ ).
        But we had to decide what is the "main order" of the magnet.


    Here we do not use the static error attribute. *ScalingPolynomBErr* is meant
    to be used for "single knob" magnets: the field scales with a single
    parameter, the magnet current. *ScalingPolynomBErr* ensures the correct
    scaling of errors without intervention, but it requires the "knob" to be
    associated with a scalar value: the strength of the main component,
    determined by the element class. For the :py:class:`.Multipole` class,
    there is no default order defined. The user has to set the
    *DefaultOrder* attribute to the order of its choice (dipole=0,
    quadrupole=1,…) and normalise the errors with this.
"""
import numpy as np
from typing import Optional, Union
from at.lattice import refpts_iterator, Lattice, Refpts
from at.lattice import shift_elem, rotate_elem
from at.physics import find_orbit, get_optics
from at.tracking import lattice_pass
from scipy.stats import truncnorm, norm


__all__ = ['find_orbit_err', 'get_optics_err', 'lattice_pass_err',
           'assign_errors', 'enable_errors']

_BPM_ATTRS = {'BPMGain': (2,), 'BPMOffset': (2,), 'BPMTilt': (1,)}
_ERR_ATTRS = {'PolynomBErr': None, 'PolynomAErr': None,
              'ScalingPolynomBErr': None, 'ScalingPolynomAErr': None,
              'ShiftErr': (2,), 'RotationErr': None}
_ALL_ATTRS = dict(**_BPM_ATTRS, **_ERR_ATTRS)

_SEL_ARGS = ('all', 'shiftx', 'shifty', 'tilt', 'pitch', 'yaw',
             'PolynomB', 'PolynomA', 'IndexB', 'IndexA')


def _truncated_randn(truncation=None, **kwargs):
    if truncation is not None:
        return truncnorm.rvs(-truncation, truncation, **kwargs)
    else:
        return norm.rvs(**kwargs)


def assign_errors(ring: Lattice, refpts: Refpts,
                  truncation: Optional[float] = None,
                  seed: Optional[Union[int, np.random.Generator]] = None,
                  **kwargs):
    # noinspection PyUnresolvedReferences
    r"""Assign errors to selected elements

    The errors are stored as additional attributes but are not enabled for
    tracking (see :py:func:`enable_errors`).

    Args:
        ring:       Lattice description.
        refpts:     Element selector. May be:

          #. an integer or a sequence of integers
             (0 indicating the first element)
          #. a sequence of booleans marking the selected elements
        truncation:     Truncation of the Gaussian error distribution at +/-
          *truncation* * :math:`\sigma`
        seed:   Seed for the random generator. It *seed* is :py:obj:`None`, the
          :py:obj:`numpy.random.RandomState` singleton is used. If seed is an
          :py:class:`int`, a new :py:class:`~numpy.random.RandomState` instance
          is used. If seed is already a :py:class:`~numpy.random.Generator`
          like :py:obj:`at.random.common` then that instance is used.

    Other keyword arguments specify the kind of errors to be assigned. Error
    definitions may be given in 2 forms:

    * **a tuple of values**: (*systematic*, *random*). The *systematic* value
      is applied unchanged to all the selected elements, the *random* value is
      taken as the standard deviation of the generated error distribution,
    * **a single value**: it acts as the *random* part of the previous form,
      and there is no systematic error.

    .. rubric:: Monitor errors:

    See :ref:`monitor-errors` for a definition of monitor errors.

    Keyword Args:
        BPMOffset:  Offsets may be:

          * :py:class:`float` or (1,) float array: the same offset is applied
            in both planes to all elements
          * (2,) float array: [offset_x, offset_y] applied to all elements
          * (nelems, 1) or (nelems, 2) array: assign one value per element
            (this may be useful for systematic errors)
        BPMGain:    Monitor gain (scaling factor)

          * :py:class:`float` or (1,) float array: the same gain is applied
            in both planes to all elements
          * (2,) float array: [gain_x, gain_y] applied to all elements
          * (nelems, 1) or (nelems, 2) array: assign one value per element
            (this may be useful for systematic errors)
        BPMTilt:    :py:class:`float`, (1,) or (nelems, 1) float array

    .. rubric:: Magnet errors:

    See :ref:`magnet-alignment-errors` and :ref:`magnet-field-errors` for
    a definition of monitor errors.

    Keyword Args:
        ShiftErr:       Magnet shift [m]. Maybe:

          * :py:class:`float` or (1,) float array: the same shift is applied
            in both planes to all elements
          * (2,) float array: [shift\ :sub:`x`, shift\ :sub:`y`\ ] applied to
            all elements
          * (nelems, 1) or (nelems, 2) array: assign one value per element
            (this may be useful for systematic errors)
        RotationErr:    Magnet rotation

          * :py:class:`float` or (1,) float array: tilt error, no pitch nor yaw
          * (3,) float array: [tilt, pitch, yaw] rotations applied to all
            elements
          * (nelems, 1) or (nelems, 3) array: assign one value per element
            (this may be useful for systematic errors)
        PolynomBErr:    Absolute field error. *PolynomAErr* is added to the
          magnet's *PolynomB*
        PolynomAErr:    Absolute field error. *PolynomBErr* is added to the
          magnet's *PolynomA*
        ScalingPolynomBErr:    Field error. *ScalingPolynomBErr* is the
          multipolar field error relative to the main magnet field component.
          When :py:func:`enabling the errors<enable_errors>`,
          *ScalingPolynomBErr* is multiplied by the magnet strengh and added tp
          *PolynomB*
        ScalingPolynomAErr:    Field error. *ScalingPolynomAErr* is the skew
          multipolar field error relative to the main magnet field component.

    Examples:

        >>> qpoles =ring.get_cells(checktype(Quadrupole))
        >>> shift_err = 0.0001      # 100 um random position error (both planes)
        >>> rotation_err = 0.0002   # 200 urad random tilt error (both planes)
        >>> syst_PBErr = [0, 0, 0, 98]  # systematic octupole component
        >>> rand_PBErr = [0, 0.001]     # 1.e-3 relative gradient error
        >>> assign_errors(ring, qpoles,
        ... ShiftErr=shift_err,
        ... RotationErr=rotation_err,
        ... ScalingPolynomBErr=(syst_PBErr, rand_PBErr))



    See also:
        :py:func:`enable_errors`, :py:func:`get_optics_err`
    """
    elements = ring[refpts]
    for attr, sz in _ALL_ATTRS.items():
        val = kwargs.pop(attr, None)
        if val is not None:
            if isinstance(val, tuple):
                syst, rand = val
                rand = np.atleast_2d(rand)
                syst = np.atleast_2d(syst)
            else:
                rand = np.atleast_2d(val)
                syst = np.zeros(rand.shape)
            if sz is None:
                szsyst = syst.shape[1:]
                szrand = rand.shape[1:]
                # pad syst and rand to the same size
                szmax = np.maximum(szsyst, szrand)
                missyst = np.concatenate(([0], szmax-szsyst))
                misrand = np.concatenate(([0], szmax-szrand))
                rand = np.pad(rand, tuple((0, m) for m in misrand))
                syst = np.pad(syst, tuple((0, m) for m in missyst))
                sz = tuple(szmax)
            rv = _truncated_randn(size=((len(elements),) + sz),
                                  truncation=truncation, random_state=seed)
            try:
                vals = syst + rv*rand
            except Exception as exc:
                exc.args = ('Attribute {0} does not accept value {1}: {2}'.
                            format(attr, val, exc),)
                raise
            for el, val in zip(elements, vals):
                setattr(el, attr, val)


def _rotmat(theta):
    cs = np.cos(theta)
    sn = np.sin(theta)
    return np.array([[cs, sn], [-sn, cs]])


def _apply_bpm_orbit_error(ring, refpts, orbit):
    for e, o6 in zip(refpts_iterator(ring, refpts), orbit):
        o6 = o6.reshape((-1, 6))
        if hasattr(e, 'BPMOffset'):
            o6[:, [0, 2]] -= e.BPMOffset
        if hasattr(e, 'BPMTilt'):
            o6[:, [0, 2]] = o6[:, [0, 2]] @ _rotmat(e.BPMTilt).T
        if hasattr(e, 'BPMGain'):
            o6[:, [0, 2]] *= e.BPMGain


def _apply_bpm_track_error(ring, refpts, trajectory):
    for traj in trajectory.T:
        _apply_bpm_orbit_error(ring, refpts, traj)


def _apply_alignment_errors(ring, **kwargs):
    refpts = [(hasattr(e, 'ShiftErr') or hasattr(e, 'RotationErr'))
              for e in ring]
    ring = ring.replace(refpts)
    alldef = kwargs.pop('all', True)
    for e in ring[refpts]:
        shift = getattr(e, 'ShiftErr')
        rots = getattr(e, 'RotationErr')
        if shift is not None:
            shiftx = kwargs.pop('shiftx', alldef)*shift[0]
            shifty = kwargs.pop('shifty', alldef)*shift[1]
            shift_elem(e, shiftx, shifty, relative=True)
        if rots is not None:
            tilt = kwargs.pop('tilt', alldef)*rots[0]
            pitch = kwargs.pop('pitch', alldef) * rots[1]
            yaw = kwargs.pop('yaw', alldef) * rots[2]
            rotate_elem(e, tilt=tilt, pitch=pitch,
                        yaw=yaw, relative=True)
    return ring


def _apply_field_errors(ring, **kwargs):
    def sanitize(e):
        la = len(e.PolynomA)
        lb = len(e.PolynomB)
        mo = max(la, lb)
        e.PolynomA = np.pad(e.PolynomA, (0, mo - la))
        e.PolynomB = np.pad(e.PolynomB, (0, mo - lb))
        e.MaxOrder = mo - 1

    def get_pol(e, pname, pstatic, pdynamic, index):
        def get_err(elem, attribute, idx):
            empty = np.array([], dtype=float)
            v = getattr(elem, attribute, empty)
            if not (idx is None or idx >= len(v)):
                tmp = v[idx]
                v = np.zeros(idx+1)
                v[idx] = tmp
            return v

        value = getattr(e, pname)
        staticerr = get_err(e, pstatic, index)
        dynamicerr = get_err(e, pdynamic, index)
        pn = np.zeros(max(len(value), len(staticerr), len(dynamicerr)))
        pn[:len(value)] += value
        pn[:len(staticerr)] += staticerr
        pn[:len(dynamicerr)] += e.strength*dynamicerr
        return pn

    def set_polerr(ring, pname, index):
        pstat = pname+'Err'
        pdyn = 'Scaling' + pstat
        refpts = [hasattr(e, pname) and (hasattr(e, pstat) or
                                         hasattr(e, pdyn)) for e in ring]
        rr = ring.replace(refpts)
        for e in rr[refpts]:
            setattr(e, pname, get_pol(e, pname, pstat, pdyn, index))
            sanitize(e)
        return rr

    alldef = kwargs.pop('all', True)
    for pol in ['A', 'B']:
        if kwargs.pop('Polynom'+pol, alldef):
            index = kwargs.pop('Index'+pol, None)
            ring = set_polerr(ring, 'Polynom'+pol, index)
    return ring
    

def enable_errors(ring: Lattice, **kwargs):
    r"""Enable magnet errors

    Returns a shallow copy of *ring* where magnet errors defined by
    :py:func:`assign_errors` are introduced in the magnet attributes.

    By default, all assigned errors are enabled, but keyword arguments allow a
    selection of the enabled errors.

    Args:
        ring:   Lattice description.

    Keyword Args:
        all (bool):         Set the default value for all the specific error
          flags. Default: :py:obj:`True`
        shiftx (bool):      enable horizontal shift errors. Default: *all*
        shifty (bool):      enable vertical shift errors. Default: *all*
        tilt (bool):        enable tilt errors. Default: *all*
        pitch (bool):       enable pitch errors. Default: *all*
        yaw (bool):         enable yaw errors. Default: *all*
        PolynomB (bool):    enable polynomial errors. Default: *all*
        IndexB (Optional[int]): restrict the polynomial errors to the
          specified index. Default: :py:obj:`None` meaning the whole polynom
        PolynomA (bool):    enable polynomial errors. Default: *all*
        IndexA (Optional[int]): restrict the skew polynomial error to the
          specified index. Default: :py:obj:`None` meaning the whole polynom

    Examples:
        >>> ringerr = enable_errors(ring)

        All errors are enabled in *ringerr*

        >>> ringerr = enable_errors(all=False, ShiftErr=True)

        Only magnet shift errors are active

        >>> ringerr = enable_errors(all=False)

        No magnet errors are enabled. Only monitor errors will be active.

    See also:
        :py:func:`assign_errors`, :py:func:`get_optics_err`
    """
    if not ring.has_errors:
        ring = _apply_field_errors(ring, **kwargs)
        ring = _apply_alignment_errors(ring, **kwargs)
        ring._has_errors = True
    return ring


def has_errors(ring):
    """Get the error status of a lattice"""
    return getattr(ring, '_has_errors', False)


def get_mean_std_err(ring: Lattice, key, attr, index=0):
    vals = [np.atleast_1d(getattr(e, attr, 0.0))[index]
            for e in ring.get_elements(key)]
    return np.mean(vals), np.std(vals)


def _sort_flags(kwargs):
    errargs = {}
    for key in _SEL_ARGS:
        if key in kwargs:
            errargs[key] = kwargs.pop(key)
    return kwargs, errargs


def find_orbit_err(ring: Lattice, refpts: Refpts = None, **kwargs):
    """Find the closed orbit if a lattice with errors

    :py:func:`find_orbit_err` enables the selected errors, finds the closed
    orbit and modifies the result according to monitor errors.
    The *ring* :py:class:`~.Lattice` is not modified.

    Args:
        ring:       Lattice description
        refpts:

    The *all*, *ShiftErr*, *RotationErr*, *PolynomBErr*, *PolynomBIndex*,
    *PolynomAErr*, *PolynomAIndex* keywords are defined as in
    :py:func:`enable_errors`

    All other keywords are forwarded to :py:func:`.find_orbit`

    See also:
        :py:func:`assign_errors`, :py:func:`.find_orbit`,
        :py:func:`get_optics_err`, :py:func:`lattice_pass_err`
    """
    kwargs, errargs = _sort_flags(kwargs)
    ring = enable_errors(ring, **errargs)
    orbit0, orbit = find_orbit(ring, refpts=refpts, **kwargs)
    _apply_bpm_orbit_error(ring, refpts, orbit)
    return orbit0, orbit


def get_optics_err(ring: Lattice, refpts: Refpts = None, **kwargs):
    """Linear analysis of a lattice with errors

    :py:func:`get_optics_err` enables the selected errors, makes the linear
    analysis of the modified :py:class:`~.Lattice` and modifies the closed
    orbit according to monitor errors.
    The *ring* :py:class:`~.Lattice` is not modified.

    Args:
        ring:       Lattice description
        refpts:

    The *all*, *ShiftErr*, *RotationErr*, *PolynomBErr*, *PolynomBIndex*,
    *PolynomAErr*, *PolynomAIndex* keywords are defined as in
    :py:func:`enable_errors`

    All other keywords are forwarded to :py:func:`.get_optics`

    See also:
        :py:func:`assign_errors`, :py:func:`.get_optics`,
        :py:func:`find_orbit_err`, :py:func:`lattice_pass_err`
    """
    kwargs, errargs = _sort_flags(kwargs)
    ring = enable_errors(ring, **errargs)
    ld0, bd, ld = get_optics(ring, refpts=refpts, **kwargs)
    _apply_bpm_orbit_error(ring, refpts, ld.closed_orbit)
    return ld0, bd, ld


def lattice_pass_err(ring: Lattice, r_in, nturns: int = 1,
                     refpts: Refpts = None, **kwargs):
    """Tracking through a lattice with errors

    :py:func:`lattice_pass_err` enables the selected errors, and tracks through
    the modified :py:class:`~.Lattice`. The coordinates on monitors are modified
    according to monitor errors.
    The *ring* :py:class:`~.Lattice` is not modified.

    Parameters:
        ring:                   lattice description
        r_in:                   (6, N) array: input coordinates of N particles.
          *r_in* is modified in-place and reports the coordinates at
          the end of the element. For the best efficiency, *r_in*
          should be given as *F_CONTIGUOUS* numpy array.
        nturns:                 number of turns to be tracked
        refpts:                 numpy array of indices of elements where
          output is desired:

          * len(line) means end of the last element (default)
          * 0 means entrance of the first element

    The *all*, *ShiftErr*, *RotationErr*, *PolynomBErr*, *PolynomBIndex*,
    *PolynomAErr*, *PolynomAIndex* keywords are defined as in
    :py:func:`enable_errors`

    All other keywords are forwarded to :py:func:`.lattice_pass`

    See also:
        :py:func:`assign_errors`, :py:func:`.lattice_pass`,
        :py:func:`get_optics_err`, :py:func:`find_orbit_err`
    """
    kwargs, errargs = _sort_flags(kwargs)
    ring = enable_errors(ring, **errargs)
    rout = lattice_pass(ring, r_in, nturns, refpts, **kwargs)
    _apply_bpm_track_error(ring, refpts, rout)
    return rout


Lattice.assign_errors = assign_errors
Lattice.find_orbit_err = find_orbit_err
Lattice.get_optics_err = get_optics_err
Lattice.enable_errors = enable_errors
Lattice.has_errors = property(has_errors, doc="Error status")
