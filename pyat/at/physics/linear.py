"""
Coupled or non-coupled 4x4 linear motion
"""
import numpy
from numpy.core.records import fromarrays
from math import sqrt, pi, sin, cos, atan2
from scipy.constants import c as clight
from scipy.linalg import solve, block_diag
from at.lattice import get_rf_frequency, set_rf_frequency, DConstant, get_s_pos
from at.lattice import Lattice, check_radiation, bool_refpts
from at.tracking import lattice_pass
from at.physics import find_orbit4, find_orbit6, find_m44, find_m66
from at.physics import a_matrix, jmat
from .harmonic_analysis import get_tunes_harmonic

__all__ = ['linopt', 'linopt2', 'linopt4', 'avlinopt', 'get_mcf',
           'get_tune', 'get_chrom']

_jmt = jmat(1)
_S2 = numpy.array([[0, 1], [-1, 0]], dtype=numpy.float64)
_Tn = [_S2, _S2, _S2.T]

# dtype for structured array containing linopt parameters
_DATA1_DTYPE = [('alpha', numpy.float64, (2,)),
                ('beta', numpy.float64, (2,)),
                ('mu', numpy.float64, (2,)),
                ('gamma', numpy.float64),
                ('A', numpy.float64, (2, 2)),
                ('B', numpy.float64, (2, 2)),
                ('C', numpy.float64, (2, 2))
                ]

_DATA2_DTYPE = [('alpha', numpy.float64, (2,)),
                ('beta', numpy.float64, (2,)),
                ('mu', numpy.float64, (2,))
                ]

_DATA4_DTYPE = [('alpha', numpy.float64, (2,)),
                ('beta', numpy.float64, (2,)),
                ('mu', numpy.float64, (2,)),
                ('gamma', numpy.float64)
                ]

_DATA6_DTYPE = [('alpha', numpy.float64, (2,)),
                ('beta', numpy.float64, (2,)),
                ('mu', numpy.float64, (3,)),
                ('R', numpy.float64, (3, 6, 6)),
                ('A', numpy.float64, (6, 6)),
                ('dispersion', numpy.float64, (4,)),
                ]

_DATAX_DTYPE = [('alpha', numpy.float64, (2,)),
                ('beta', numpy.float64, (2,)),
                ('mu', numpy.float64, (2,)),
                ('R', numpy.float64, (2, 4, 4)),
                ('A', numpy.float64, (4, 4)),
                ]

_W_DTYPE = [('W', numpy.float64, (2,))]

_IDX_DTYPE = [('idx', numpy.uint32)]


def _twiss22(ms, alpha0, beta0):
    """Calculate Twiss parameters from the standard 2x2 transfer matrix
    (i.e. x or y).
    """
    bbb = ms[:, 0, 1]
    aaa = ms[:, 0, 0] * beta0 - bbb * alpha0
    beta = (aaa * aaa + bbb * bbb) / beta0
    alpha = -(aaa * (ms[:, 1, 0] * beta0 - ms[:, 1, 1] * alpha0) +
              bbb * ms[:, 1, 1]) / beta0
    mu = numpy.arctan2(bbb, aaa)
    # Unwrap negative jumps in betatron phase advance
    dmu = numpy.diff(numpy.append([0], mu))
    jumps = dmu < -1.0e-3
    mu += numpy.cumsum(jumps) * 2.0 * numpy.pi
    return alpha, beta, mu


def _closure(m22):
    diff = (m22[0, 0] - m22[1, 1]) / 2.0
    sinmu = numpy.sign(m22[0, 1]) * sqrt(-m22[0, 1] * m22[1, 0] - diff * diff)
    cosmu = 0.5 * numpy.trace(m22)
    alpha = diff / sinmu
    beta = m22[0, 1] / sinmu
    return alpha, beta, cosmu + sinmu*1j


def _unwrap(mu):
    """Remove the phase jumps"""
    dmu = numpy.diff(numpy.concatenate((numpy.zeros((1, 2)), mu)), axis=0)
    jumps = dmu < -1.e-3
    mu += numpy.cumsum(jumps, axis=0) * 2.0 * numpy.pi


# noinspection PyShadowingNames,PyPep8Naming
def _linopt(ring, analyze, refpts=None, dp=None, dct=None, orbit=None,
            twiss_in=None, get_chrom=False, get_w=False, keep_lattice=False,
            cavpts=None, **kwargs):
    """"""
    def build_sigma(twin):
        """Build the initial distribution at entrance of the transfer line"""
        try:
            sigm = numpy.sum(twin.R, axis=0)
        except AttributeError:
            slices = [slice(2 * i, 2 * (i + 1)) for i in range(4)]
            ab = numpy.stack((twin.alpha, twin.beta), axis=1)
            sigm = numpy.zeros((4, 4))
            for slc, (alpha, beta) in zip(slices, ab):
                gamma = (1.0+alpha*alpha)/beta
                sigm[slc, slc] = numpy.array([[beta, -alpha], [-alpha, gamma]])
        try:
            d0 = twiss_in['dispersion']
        except KeyError:
            print('Dispersion not found in twiss_in, setting to zero')
            d0 = numpy.zeros((4,))
        return sigm, d0

    def chrom_w(ringup, ringdn, orbitup, orbitdn, refpts=None, **kwargs):
        """Compute the chromaticity and W-functions"""
        # noinspection PyShadowingNames
        def off_momentum(rng, orb0):
            mt, ms = get_matrix(rng, refpts, dp=orb0[4], orbit=orb0, **kwargs)
            vps, _, el0, els = analyze(mt, ms)
            tunes = numpy.mod(numpy.angle(vps)/2.0/pi, 1.0)
            return tunes, el0, els

        def wget(ddp, elup, eldn):
            """Compute the chromatic amplitude function"""
            alpha_up, beta_up = elup[:2]  # Extract alpha and beta
            alpha_dn, beta_dn = eldn[:2]
            db = (beta_up - beta_dn) / ddp
            mb = (beta_up + beta_dn) / 2
            da = (alpha_up - alpha_dn) / ddp
            ma = (alpha_up + alpha_dn) / 2
            ww = numpy.sqrt((da - ma / mb * db) ** 2 + (db / mb) ** 2)
            return ww

        tunesup, el0up, elsup = off_momentum(ringup, orbitup)
        tunesdn, el0dn, elsdn = off_momentum(ringdn, orbitdn)
        deltap = orbitup[4] - orbitdn[4]    # in 6D, dp comes out of find_orbit6
        chrom = (tunesup-tunesdn) / deltap
        w0 = wget(deltap, el0up, el0dn)
        ws = wget(deltap, elsup, elsdn)
        return chrom, w0, ws

    dp_step = kwargs.get('DPStep', DConstant.DPStep)
    add0 = kwargs.pop('add0', ())
    adds = kwargs.pop('adds', ())
    addtype = kwargs.pop('addtype', [])
    mname = kwargs.pop('mname', 'M')

    if twiss_in is None:
        o0up = None
        o0dn = None
        mxx = None
    else:
        if orbit is None:
            orbit = numpy.zeros((6,))
        sigma, d0 = build_sigma(twiss_in)
        mxx = sigma.dot(jmat(sigma.shape[0] // 2))
        dorbit = numpy.hstack((0.5 * dp_step * d0,
                               numpy.array([0.5 * dp_step, 0])))
        o0up = orbit+dorbit
        o0dn = orbit-dorbit

    if ring.radiation:
        get_matrix = find_m66
        get_orbit = find_orbit6
    else:
        def get_matrix(rg, *args, dp=0.0, **kwargs):
            return find_m44(rg, dp, *args, **kwargs)
        def get_orbit(rg, *args, dp=0.0, **kwargs):
            return find_orbit4(rg, dp, *args, **kwargs)

    # Get initial orbit
    orb0, orbs = get_orbit(ring, refpts, dp=dp, dct=dct, orbit=orbit,
                           keep_lattice=keep_lattice, **kwargs)
    # Get 1-turn transfer matrix
    mt, ms = get_matrix(ring, refpts, dp=orb0[4], orbit=orb0, **kwargs)
    # Perform analysis
    vps, dtype, el0, els = analyze(mt, ms, mxx=mxx)

    dms = vps.size
    tunes = numpy.mod(numpy.angle(vps) / 2.0 / pi, 1.0)
    spos = get_s_pos(ring, refpts)

    if dms >= 3:            # 6D processing
        dtype = dtype + [('closed_orbit', numpy.float64, (6,)),
                         ('M', numpy.float64, (2*dms, 2*dms)),
                         ('s_pos', numpy.float64)]
        data0 = (orb0, numpy.identity(2*dms), 0.0)
        datas = (orbs, ms, spos)
        if get_chrom or get_w:
            f0 = get_rf_frequency(ring, cavpts=cavpts)
            df = -dp_step * get_mcf(ring.radiation_off(copy=True)) * f0
            rgup = set_rf_frequency(ring, f0 + 0.5*df, cavpts=cavpts, copy=True)
            rgdn = set_rf_frequency(ring, f0 - 0.5*df, cavpts=cavpts, copy=True)
            o0up, _ = get_orbit(rgup, guess=orb0, **kwargs)
            o0dn, _ = get_orbit(rgdn, guess=orb0, **kwargs)
            if get_w:
                dtype = dtype + _W_DTYPE
                chrom, w0, ws = chrom_w(rgup, rgdn, o0up, o0dn, refpts,
                                        **kwargs)
                data0 = data0 + (w0,)
                datas = datas + (ws,)
            else:
                chrom, _, _ = chrom_w(rgup, rgdn, o0up, o0dn, **kwargs)
        else:
            chrom = numpy.NaN
        length = ring.get_s_pos(len(ring))[0]
        damping_rates = -numpy.log(numpy.absolute(vps))
        damping_times = length / clight / damping_rates
        beamdata = numpy.array((tunes, chrom, damping_times),
                               dtype=[('tune', numpy.float64, (dms,)),
                                      ('chromaticity', numpy.float64, (dms,)),
                                      ('damping_time', numpy.float64, (dms,))
                                      ]).view(numpy.recarray)
    else:               # 4D processing
        kwargs['keep_lattice'] = True
        dpup = orb0[4] + 0.5*dp_step
        dpdn = orb0[4] - 0.5*dp_step
        o0up, oup = get_orbit(ring, refpts, guess=orb0, dp=dpup, orbit=o0up,
                              **kwargs)
        o0dn, odn = get_orbit(ring, refpts, guess=orb0, dp=dpdn, orbit=o0dn,
                              **kwargs)
        d0 = (o0up - o0dn)[:4] / dp_step
        ds = numpy.array([(up - dn)[:4] / dp_step for up, dn in zip(oup, odn)])
        dtype = dtype + [('dispersion', numpy.float64, (4,)),
                         ('closed_orbit', numpy.float64, (6,)),
                         (mname, numpy.float64, (2*dms, 2*dms)),
                         ('s_pos', numpy.float64)]
        data0 = (d0, orb0, mt, get_s_pos(ring, len(ring)))
        datas = (numpy.reshape(ds, (-1, 4)),
                 numpy.reshape(orbs, (-1, 6)), ms,
                 ring.get_s_pos(ring.uint32_refpts(refpts)))
        if get_w:
            dtype = dtype + _W_DTYPE
            chrom, w0, ws = chrom_w(ring, ring, o0up, o0dn, refpts, **kwargs)
            data0 = data0 + (w0,)
            datas = datas + (ws,)
        elif get_chrom:
            chrom, _, _ = chrom_w(ring, ring, o0up, o0dn, **kwargs)
        else:
            chrom = numpy.NaN
        beamdata = numpy.array((tunes, chrom),
                               dtype=[('tune', numpy.float64, (dms,)),
                                      ('chromaticity', numpy.float64, (dms,)),
                                      ]).view(numpy.recarray)

    dtype = dtype + addtype
    elemdata0 = numpy.array(el0+data0+add0, dtype=dtype).view(numpy.recarray)
    elemdata = fromarrays(els+datas+adds, dtype=dtype)
    return elemdata0, beamdata, elemdata


@check_radiation(False)
def linopt4(ring, *args, **kwargs):
    """Perform linear analysis of a H/V coupled lattice

    elemdata0, beamdata, elemdata = linopt4(ring, refpts, **kwargs)

    PARAMETERS
        ring            lattice description.
        refpts=None     elements at which data is returned. It can be:
                        1) an integer in the range [-len(ring), len(ring)-1]
                           selecting the element according to python indexing
                           rules. As a special case, len(ring) is allowed and
                           refers to the end of the last element,
                        2) an ordered list of such integers without duplicates,
                        3) a numpy array of booleans of maximum length
                           len(ring)+1, where selected elements are True.
    KEYWORDS
        dp=0.0          momentum deviation.
        orbit           avoids looking for the closed orbit if is already known
                        ((6,) array)
        get_chrom=False compute dispersion and chromaticities. Needs computing
                        the tune and orbit at 2 different momentum deviations
                        around the central one.
        keep_lattice    Assume no lattice change since the previous tracking.
                        Defaults to False
        XYStep=1.0e-8   transverse step for numerical computation
        DPStep=1.0E-6   momentum deviation used for computation of
                        chromaticities and dispersion
        coupled=True    if False, simplify the calculations by assuming
                        no H/V coupling
        twiss_in=None   Initial twiss to compute transfer line optics of the
                        type lindata, the initial orbit in twiss_in is ignored,
                        only the beta and alpha are required other quatities
                        set to 0 if absent
        get_w=False     computes chromatic amplitude functions (W) [4], need to
                        compute the optics at 2 different momentum deviations
                        around the central one.
    OUTPUT
        lindata0        linear optics data at the entrance/end of the ring
        tune            [tune_A, tune_B], linear tunes for the two normal modes
                        of linear motion [1]
        chrom           [ksi_A , ksi_B], chromaticities ksi = d(nu)/(dP/P).
                        Only computed if 'get_chrom' is True
        lindata         linear optics at the points refered to by refpts, if
                        refpts is None an empty lindata structure is returned.

        lindata is a record array with fields:
        idx             element index in the ring
        s_pos           longitudinal position [m]
        closed_orbit    (6,) closed orbit vector
        dispersion      (4,) dispersion vector
        W               (2,) chromatic amplitude function
                        Only computed if 'get_chrom' is True
        M               (4, 4) transfer matrix M from the beginning of ring
                        to the entrance of the element [2]
        mu              [mux, muy], betatron phase (modulo 2*pi)
        beta            [betax, betay] vector
        alpha           [alphax, alphay] vector
        A               (2, 2) matrix A in [3]
        B               (2, 2) matrix B in [3]
        C               (2, 2) matrix C in [3]
        gamma           gamma parameter of the transformation to eigenmodes
        All values given at the entrance of each element specified in refpts.
        Field values can be obtained with either
        lindata['idx']    or
        lindata.idx
    REFERENCES
        [1] D.Edwards,L.Teng IEEE Trans.Nucl.Sci. NS-20, No.3, p.885-888, 1973
        [2] E.Courant, H.Snyder
        [3] D.Sagan, D.Rubin Phys.Rev.Spec.Top.-Accelerators and beams,
            vol.2 (1999)
        [4] Brian W. Montague Report LEP Note 165, CERN, 1979
    """
    def _analyze4(m44, mstack, mxx=None):

        def grp1(t12):
            mm = t12[:2, :2]
            nn = t12[2:, 2:]
            m = t12[:2, 2:]
            n = t12[2:, :2]
            gamma = sqrt(numpy.linalg.det(numpy.dot(n, C) + g*nn))
#           e12 = (g * mm - m.dot(_jmt.dot(C.T.dot(_jmt.T)))) / gamma
#           f12 = (n.dot(C) + g * nn) / gamma
            e12 = (g * mm - m @ _jmt @ C.T @ _jmt.T) / gamma
            f12 = (n @ C + g * nn) / gamma
            return e12, f12, gamma

        mxx = m44 if mxx is None else mxx
        M = mxx[:2, :2]
        N = mxx[2:, 2:]
        m = mxx[:2, 2:]
        n = mxx[2:, :2]
#       H = m + _jmt.dot(n.T.dot(_jmt.T))
        H = m + _jmt @ n.T @ _jmt.T
        detH = numpy.linalg.det(H)
        if detH == 0.0:
            g = 1.0
            C = -H
            A = M
            B = N
        else:
            t = numpy.trace(M - N)
            t2 = t * t
            t2h = t2 + 4.0 * detH
            g2 = (1.0 + sqrt(t2 / t2h)) / 2
            g = sqrt(g2)
            C = -H * numpy.sign(t) / (g * sqrt(t2h))
            A = g2*M - g*(m.dot(_jmt.dot(C.T.dot(_jmt.T))) + C.dot(n)) + \
                C.dot(N.dot(_jmt.dot(C.T.dot(_jmt.T))))
            B = g2*N + g*(_jmt.dot(C.T.dot(_jmt.T.dot(m))) + n.dot(C)) + \
                _jmt.dot(C.T.dot(_jmt.T.dot(M.dot(C))))
        alp0_a, bet0_a, vp_a = _closure(A)
        alp0_b, bet0_b, vp_b = _closure(B)
        vps = numpy.array([vp_a, vp_b])
        el0 = (numpy.array([alp0_a, alp0_b]),
               numpy.array([bet0_a, bet0_b]),
               numpy.mod(numpy.angle(vps), 2.0*pi), g)
        if mstack.shape[0] > 0:
            e, f, g = zip(*[grp1(mi) for mi in mstack])
            alp_a, bet_a, mu_a = _twiss22(numpy.array(e), alp0_a, bet0_a)
            alp_b, bet_b, mu_b = _twiss22(numpy.array(f), alp0_b, bet0_b)
            els = (numpy.stack((alp_a, alp_b), axis=1),
                   numpy.stack((bet_a, bet_b), axis=1),
                   numpy.stack((mu_a, mu_b), axis=1), numpy.array(g))
        else:
            els = (numpy.empty((0, 2)), numpy.empty((0, 2)),
                   numpy.empty((0, 2)), numpy.empty((0,)))
        return vps, _DATA4_DTYPE, el0, els

    return _linopt(ring, _analyze4, *args, **kwargs)


@check_radiation(False)
def linopt2(ring, *args, **kwargs):
    """Perform linear analysis of an uncoupled lattice

    elemdata0, beamdata, elemdata = linopt2(ring, refpts, **kwargs)

    PARAMETERS
        ring            lattice description.
        refpts=None     elements at which data is returned. It can be:
                        1) an integer in the range [-len(ring), len(ring)-1]
                           selecting the element according to python indexing
                           rules. As a special case, len(ring) is allowed and
                           refers to the end of the last element,
                        2) an ordered list of such integers without duplicates,
                        3) a numpy array of booleans of maximum length
                           len(ring)+1, where selected elements are True.
    KEYWORDS
        dp=0.0          momentum deviation.
        orbit           avoids looking for the closed orbit if is already known
                        ((6,) array)
        get_chrom=False compute dispersion and chromaticities. Needs computing
                        the tune and orbit at 2 different momentum deviations
                        around the central one.
        keep_lattice    Assume no lattice change since the previous tracking.
                        Defaults to False
        XYStep=1.0e-8   transverse step for numerical computation
        DPStep=1.0E-6   momentum deviation used for computation of
                        chromaticities and dispersion
        twiss_in=None   Initial twiss to compute transfer line optics of the
                        type lindata, the initial orbit in twiss_in is ignored,
                        only the beta and alpha are required other quatities
                        set to 0 if absent
        get_w=False     computes chromatic amplitude functions (W) [4], need to
                        compute the optics at 2 different momentum deviations
                        around the central one.
    OUTPUT
        lindata0        linear optics data at the entrance/end of the ring
        tune            [tune_A, tune_B], linear tunes for the two normal modes
                        of linear motion [1]
        chrom           [ksi_A , ksi_B], chromaticities ksi = d(nu)/(dP/P).
                        Only computed if 'get_chrom' is True
        lindata         linear optics at the points refered to by refpts, if
                        refpts is None an empty lindata structure is returned.

        lindata is a record array with fields:
        idx             element index in the ring
        s_pos           longitudinal position [m]
        closed_orbit    (6,) closed orbit vector
        dispersion      (4,) dispersion vector
        W               (2,) chromatic amplitude function
                        Only computed if 'get_chrom' is True
        M               (4, 4) transfer matrix M from the beginning of ring
                        to the entrance of the element [2]
        mu              [mux, muy], betatron phase (modulo 2*pi)
        beta            [betax, betay] vector
        alpha           [alphax, alphay] vector
        All values given at the entrance of each element specified in refpts.
        Field values can be obtained with either
        lindata['idx']    or
        lindata.idx
    REFERENCES
        [1] D.Edwards,L.Teng IEEE Trans.Nucl.Sci. NS-20, No.3, p.885-888, 1973
        [2] E.Courant, H.Snyder
        [3] D.Sagan, D.Rubin Phys.Rev.Spec.Top.-Accelerators and beams,
            vol.2 (1999)
        [4] Brian W. Montague Report LEP Note 165, CERN, 1979
    """
    def _analyze2(m44, mstack, mxx=None):
        mxx = m44 if mxx is None else mxx
        A = mxx[:2, :2]
        B = mxx[2:, 2:]
        alp0_a, bet0_a, vp_a = _closure(A)
        alp0_b, bet0_b, vp_b = _closure(B)
        vps = numpy.array([vp_a, vp_b])
        el0 = (numpy.array([alp0_a, alp0_b]),
               numpy.array([bet0_a, bet0_b]),
               numpy.mod(numpy.angle(vps), 2.0*pi))
        alpha_a, beta_a, mu_a = _twiss22(mstack[:, :2, :2], alp0_a, bet0_a)
        alpha_b, beta_b, mu_b = _twiss22(mstack[:, 2:, 2:], alp0_b, bet0_b)
        els = (numpy.stack((alpha_a, alpha_b), axis=1),
               numpy.stack((beta_a, beta_b), axis=1),
               numpy.stack((mu_a, mu_b), axis=1))
        return vps, _DATA2_DTYPE, el0, els

    return _linopt(ring, _analyze2, *args, **kwargs)


# noinspection PyPep8Naming
@check_radiation(False)
def linopt(ring, dp=0.0, refpts=None, get_chrom=False, **kwargs):
    """Perform linear analysis of a lattice

    lindata0, tune, chrom, lindata = linopt(ring, dp[, refpts])

    PARAMETERS
        ring            lattice description.
        dp=0.0          momentum deviation.
        refpts=None     elements at which data is returned. It can be:
                        1) an integer in the range [-len(ring), len(ring)-1]
                           selecting the element according to python indexing
                           rules. As a special case, len(ring) is allowed and
                           refers to the end of the last element,
                        2) an ordered list of such integers without duplicates,
                        3) a numpy array of booleans of maximum length
                           len(ring)+1, where selected elements are True.
    KEYWORDS
        orbit           avoids looking for the closed orbit if is already known
                        ((6,) array)
        get_chrom=False compute dispersion and chromaticities. Needs computing
                        the tune and orbit at 2 different momentum deviations
                        around the central one.
        keep_lattice    Assume no lattice change since the previous tracking.
                        Defaults to False
        XYStep=1.0e-8   transverse step for numerical computation
        DPStep=1.0E-6   momentum deviation used for computation of
                        chromaticities and dispersion
        coupled=True    if False, simplify the calculations by assuming
                        no H/V coupling
        twiss_in=None   Initial twiss to compute transfer line optics of the
                        type lindata, the initial orbit in twiss_in is ignored,
                        only the beta and alpha are required other quatities
                        set to 0 if absent
        get_w=False     computes chromatic amplitude functions (W) [4], need to
                        compute the optics at 2 different momentum deviations
                        around the central one.
    OUTPUT
        lindata0        linear optics data at the entrance/end of the ring
        tune            [tune_A, tune_B], linear tunes for the two normal modes
                        of linear motion [1]
        chrom           [ksi_A , ksi_B], chromaticities ksi = d(nu)/(dP/P).
                        Only computed if 'get_chrom' is True
        lindata         linear optics at the points refered to by refpts, if
                        refpts is None an empty lindata structure is returned.

        lindata is a record array with fields:
        idx             element index in the ring
        s_pos           longitudinal position [m]
        closed_orbit    (6,) closed orbit vector
        dispersion      (4,) dispersion vector
        W               (2,) chromatic amplitude function
                        Only computed if 'get_chrom' is True
        m44             (4, 4) transfer matrix M from the beginning of ring
                        to the entrance of the element [2]
        mu              [mux, muy], betatron phase (modulo 2*pi)
        beta            [betax, betay] vector
        alpha           [alphax, alphay] vector
        All values given at the entrance of each element specified in refpts.
        In case coupled = True additional outputs are available:
        A               (2, 2) matrix A in [3]
        B               (2, 2) matrix B in [3]
        C               (2, 2) matrix C in [3]
        gamma           gamma parameter of the transformation to eigenmodes
        Field values can be obtained with either
        lindata['idx']    or
        lindata.idx
    REFERENCES
        [1] D.Edwards,L.Teng IEEE Trans.Nucl.Sci. NS-20, No.3, p.885-888, 1973
        [2] E.Courant, H.Snyder
        [3] D.Sagan, D.Rubin Phys.Rev.Spec.Top.-Accelerators and beams,
            vol.2 (1999)
        [4] Brian W. Montague Report LEP Note 165, CERN, 1979
    """
    def _analyze2(m44, mstack, mxx=None):
        mxx = m44 if mxx is None else mxx
        A = mxx[:2, :2]
        B = mxx[2:, 2:]
        alp0_a, bet0_a, vp_a = _closure(A)
        alp0_b, bet0_b, vp_b = _closure(B)
        vps = numpy.array([vp_a, vp_b])
        el0 = (numpy.array([alp0_a, alp0_b]),
               numpy.array([bet0_a, bet0_b]),
               numpy.mod(numpy.angle(vps), 2.0*pi), numpy.NaN,
               numpy.broadcast_to(numpy.NaN, (2, 2)),
               numpy.broadcast_to(numpy.NaN, (2, 2)),
               numpy.broadcast_to(numpy.NaN, (2, 2)))
        alpha_a, beta_a, mu_a = _twiss22(mstack[:, :2, :2], alp0_a, bet0_a)
        alpha_b, beta_b, mu_b = _twiss22(mstack[:, 2:, 2:], alp0_b, bet0_b)
        nrefs = mstack.shape[0]
        els = (numpy.stack((alpha_a, alpha_b), axis=1),
               numpy.stack((beta_a, beta_b), axis=1),
               numpy.stack((mu_a, mu_b), axis=1),
               numpy.broadcast_to(numpy.NaN, (nrefs,)),
               numpy.broadcast_to(numpy.NaN, (nrefs, 2, 2)),
               numpy.broadcast_to(numpy.NaN, (nrefs, 2, 2)),
               numpy.broadcast_to(numpy.NaN, (nrefs, 2, 2)))
        return vps, _DATA1_DTYPE, el0, els

    def _analyze4(m44, mstack, mxx=None):
        def grp1(t12):
            mm = t12[:2, :2]
            nn = t12[2:, 2:]
            m = t12[:2, 2:]
            n = t12[2:, :2]
            gamma = sqrt(numpy.linalg.det(numpy.dot(n, C) + g*nn))
            e12 = (g * mm - m.dot(_jmt.dot(C.T.dot(_jmt.T)))) / gamma
            f12 = (n.dot(C) + g * nn) / gamma
            a12 = e12.dot(A.dot(_jmt.dot(e12.T.dot(_jmt.T))))
            b12 = f12.dot(B.dot(_jmt.dot(f12.T.dot(_jmt.T))))
            c12 = numpy.dot(mm.dot(C) + g*m, _jmt.dot(f12.T.dot(_jmt.T)))
            return e12, f12, gamma, a12, b12, c12

        mxx = m44 if mxx is None else mxx
        M = mxx[:2, :2]
        N = mxx[2:, 2:]
        m = mxx[:2, 2:]
        n = mxx[2:, :2]
        H = m + _jmt.dot(n.T.dot(_jmt.T))
        detH = numpy.linalg.det(H)
        if detH == 0.0:
            g = 1.0
            C = -H
            A = M
            B = N
        else:
            t = numpy.trace(M - N)
            t2 = t * t
            t2h = t2 + 4.0 * detH
            g2 = (1.0 + sqrt(t2 / t2h)) / 2
            g = sqrt(g2)
            C = -H * numpy.sign(t) / (g * sqrt(t2h))
            A = g2*M - g*(m.dot(_jmt.dot(C.T.dot(_jmt.T))) + C.dot(n)) + \
                C.dot(N.dot(_jmt.dot(C.T.dot(_jmt.T))))
            B = g2*N + g*(_jmt.dot(C.T.dot(_jmt.T.dot(m))) + n.dot(C)) + \
                _jmt.dot(C.T.dot(_jmt.T.dot(M.dot(C))))
        alp0_a, bet0_a, vp_a = _closure(A)
        alp0_b, bet0_b, vp_b = _closure(B)
        vps = numpy.array([vp_a, vp_b])
        inival = (numpy.array([alp0_a, alp0_b]),
                  numpy.array([bet0_a, bet0_b]),
                  numpy.mod(numpy.angle(vps), 2.0*pi), g, A, B, C)
        if mstack.shape[0] > 0:
            e, f, g, ai, bi, ci = zip(*[grp1(mi) for mi in mstack])
            alp_a, bet_a, mu_a = _twiss22(numpy.array(e), alp0_a, bet0_a)
            alp_b, bet_b, mu_b = _twiss22(numpy.array(f), alp0_b, bet0_b)
            val = (numpy.stack((alp_a, alp_b), axis=1),
                   numpy.stack((bet_a, bet_b), axis=1),
                   numpy.stack((mu_a, mu_b), axis=1), numpy.array(g),
                   numpy.stack(ai, axis=0), numpy.stack(bi, axis=0),
                   numpy.stack(ci, axis=0))
        else:
            val = (numpy.empty((0, 2)), numpy.empty((0, 2)),
                   numpy.empty((0, 2)), numpy.empty((0,)),
                   numpy.empty((0, 2, 2)),
                   numpy.empty((0, 2, 2)), numpy.empty((0, 2, 2)))
        return vps, _DATA1_DTYPE, inival, val

    kwargs['add0'] = (0,)
    kwargs['adds'] = (ring.uint32_refpts(refpts),)
    kwargs['addtype'] = [('idx', numpy.uint32)]

    analyze = _analyze4 if kwargs.pop('coupled', True) else _analyze2
    eld0, bd, eld = _linopt(ring, analyze, refpts, dp=dp, get_chrom=get_chrom,
                            mname='m44', **kwargs)
    return eld0, bd.tune, bd.chromaticity, eld


# noinspection PyPep8Naming
@check_radiation(False)
def avlinopt(ring, dp=0.0, refpts=None, **kwargs):
    """Perform linear analysis of a lattice and returns average beta, dispersion
    and phase advance

    lindata,avebeta,avemu,avedisp,tune,chrom = avlinopt(ring, dp[, refpts])

    PARAMETERS
        ring            lattice description.
        dp=0.0          momentum deviation.
        refpts=None     elements at which data is returned. It can be:
                        1) an integer in the range [-len(ring), len(ring)-1]
                           selecting the element according to python indexing
                           rules. As a special case, len(ring) is allowed and
                           refers to the end of the last element,
                        2) an ordered list of such integers without duplicates,
                        3) a numpy array of booleans of maximum length
                           len(ring)+1, where selected elements are True.

    KEYWORDS
        orbit           avoids looking for the closed orbit if is already known
                        ((6,) array)
        keep_lattice    Assume no lattice change since the previous tracking.
                        Defaults to False
        XYStep=1.0e-8   transverse step for numerical computation
        DPStep=1.0E-8   momentum deviation used for computation of
                        chromaticities and dispersion
        coupled=True    if False, simplify the calculations by assuming
                        no H/V coupling

    OUTPUT
        lindata         linear optics at the points refered to by refpts, if
                        refpts is None an empty lindata structure is returned.
                        See linopt for details
        avebeta         Average beta functions [betax,betay] at refpts
        avemu           Average phase advances [mux,muy] at refpts
        avedisp         Average dispersion [Dx,Dx',Dy,Dy',muy] at refpts
        avespos         Average s position at refpts
        tune            [tune_A, tune_B], linear tunes for the two normal modes
                        of linear motion [1]
        chrom           [ksi_A , ksi_B], chromaticities ksi = d(nu)/(dP/P).
                        Only computed if 'get_chrom' is True


    See also get_twiss,linopt

    """
    def get_strength(elem):
        try:
            k = elem.PolynomB[1]
        except (AttributeError, IndexError):
            k = 0.0
        return k

    def betadrift(beta0, beta1, alpha0, lg):
        gamma0 = (alpha0 * alpha0 + 1) / beta0
        return 0.5 * (beta0 + beta1) - gamma0 * lg * lg / 6

    def betafoc(beta1, alpha0, alpha1, k2, lg):
        gamma1 = (alpha1 * alpha1 + 1) / beta1
        return 0.5 * ((gamma1 + k2 * beta1) * lg + alpha1 - alpha0) / k2 / lg

    def dispfoc(dispp0, dispp1, k2, lg):
        return (dispp0 - dispp1) / k2 / lg

    boolrefs = bool_refpts([] if refpts is None else refpts, len(ring))
    length = numpy.array([el.Length for el in ring[boolrefs]])
    strength = numpy.array([get_strength(el) for el in ring[boolrefs]])
    longelem = bool_refpts([], len(ring))
    longelem[boolrefs] = (length != 0)

    shorti_refpts = (~longelem) & boolrefs
    longi_refpts = longelem & boolrefs
    longf_refpts = numpy.roll(longi_refpts, 1)

    all_refs = shorti_refpts | longi_refpts | longf_refpts
    _, tune, chrom, d_all = linopt(ring, dp=dp, refpts=all_refs,
                                   get_chrom=True, **kwargs)
    lindata = d_all[boolrefs[all_refs]]

    avebeta = lindata.beta.copy()
    avemu = lindata.mu.copy()
    avedisp = lindata.dispersion.copy()
    aves = lindata.s_pos.copy()

    di = d_all[longi_refpts[all_refs]]
    df = d_all[longf_refpts[all_refs]]

    long = (length != 0.0)
    kfoc = (strength != 0.0)
    foc = long & kfoc
    nofoc = long & (~kfoc)
    K2 = numpy.stack((strength[foc], -strength[foc]), axis=1)
    fff = foc[long]
    length = length.reshape((-1, 1))

    avemu[long] = 0.5 * (di.mu + df.mu)
    aves[long] = 0.5 * (df.s_pos + di.s_pos)
    avebeta[nofoc] = \
        betadrift(di.beta[~fff], df.beta[~fff], di.alpha[~fff], length[nofoc])
    avebeta[foc] = \
        betafoc(df.beta[fff], di.alpha[fff], df.alpha[fff], K2, length[foc])
    avedisp[numpy.ix_(long, [1, 3])] = \
        (df.dispersion[:, [0, 2]] - di.dispersion[:, [0, 2]]) / length[long]
    idx = numpy.ix_(~fff, [0, 2])
    avedisp[numpy.ix_(nofoc, [0, 2])] = (di.dispersion[idx] +
                                         df.dispersion[idx]) * 0.5
    idx = numpy.ix_(fff, [1, 3])
    avedisp[numpy.ix_(foc, [0, 2])] = \
        dispfoc(di.dispersion[idx], df.dispersion[idx], K2, length[foc])
    return lindata, avebeta, avemu, avedisp, aves, tune, chrom


@check_radiation(False)
def get_mcf(ring, dp=0.0, keep_lattice=False, **kwargs):
    """Compute momentum compaction factor

    PARAMETERS
        ring            lattice description
        dp              momentum deviation. Defaults to 0

    KEYWORDS
        keep_lattice    Assume no lattice change since the previous tracking.
                        Defaults to False
        dp_step=1.0E-6  momentum deviation used for differentiation
    """
    dp_step = kwargs.pop('DPStep', DConstant.DPStep)
    fp_a, _ = find_orbit4(ring, dp=dp - 0.5*dp_step, keep_lattice=keep_lattice)
    fp_b, _ = find_orbit4(ring, dp=dp + 0.5*dp_step, keep_lattice=True)
    fp = numpy.stack((fp_a, fp_b),
                     axis=0).T  # generate a Fortran contiguous array
    b = numpy.squeeze(lattice_pass(ring, fp, keep_lattice=True), axis=(2, 3))
    ring_length = get_s_pos(ring, len(ring))
    return (b[5, 1] - b[5, 0]) / dp_step / ring_length[0]


@check_radiation(False)
def get_tune(ring, method='linopt', dp=0.0, **kwargs):
    """
    gets the tune using several available methods

    method can be 'linopt', 'fft' or 'laskar'
    linopt: returns the tune from the linopt function
    fft: tracks a single particle (one for x and one for y)
    and computes the tune from the fft
    laskar: tracks a single particle (one for x and one for y)
    and computes the harmonic components


    INPUT
    for linopt:
        no input needed

    for harmonic:
        nturns: number of turn
        amplitude: amplitude of oscillation
        method: laskar or fft
        num_harmonics: number of harmonic components to compute
        (before mask applied, default=20)
        fmin/fmax: determine the boundaries within which the tune is
        located [default 0->1]
        hann: flag to turn on hanning window [default-> False]
        remove_dc: Removes the mean offset of oscillation data

    OUTPUT
        tunes = np.array([Qx,Qy])
    """

    # noinspection PyShadowingNames
    def gen_centroid(ring, ampl, nturns, dp, remove_dc):
        orbit, _ = find_orbit4(ring, dp)
        ld, _, _, _ = linopt(ring, dp, orbit=orbit)

        invx = numpy.array([[1/numpy.sqrt(ld['beta'][0]), 0],
                            [ld['alpha'][0]/numpy.sqrt(ld['beta'][0]),
                            numpy.sqrt(ld['beta'][0])]])

        invy = numpy.array([[1/numpy.sqrt(ld['beta'][1]), 0],
                            [ld['alpha'][1]/numpy.sqrt(ld['beta'][1]),
                            numpy.sqrt(ld['beta'][1])]])

        p0 = numpy.array([orbit, ]*2).T
        p0[0, 0] += ampl
        p0[2, 1] += ampl
        p1 = lattice_pass(ring, p0, refpts=len(ring), nturns=nturns)
        cent_x = p1[0, 0, 0, :]
        cent_xp = p1[1, 0, 0, :]
        cent_y = p1[2, 1, 0, :]
        cent_yp = p1[3, 1, 0, :]
        if remove_dc:
            cent_x -= numpy.mean(cent_x)
            cent_y -= numpy.mean(cent_y)
            cent_xp -= numpy.mean(cent_xp)
            cent_yp -= numpy.mean(cent_yp)

        cent_x, cent_xp = numpy.matmul(invx, [cent_x, cent_xp])
        cent_y, cent_yp = numpy.matmul(invy, [cent_y, cent_yp])
        return (cent_x - 1j * cent_xp,
                cent_y - 1j * cent_yp)

    if method == 'linopt':
        _, tunes, _, _ = linopt(ring, dp=dp)
    else:
        nturns = kwargs.pop('nturns', 512)
        ampl = kwargs.pop('ampl', 1.0e-6)
        remove_dc = kwargs.pop('remove_dc', True)
        cent_x, cent_y = gen_centroid(ring, ampl, nturns, dp, remove_dc)
        cents = numpy.vstack((cent_x, cent_y))
        tunes = get_tunes_harmonic(cents, method, **kwargs)
    return tunes


@check_radiation(False)
def get_chrom(ring, method='linopt', dp=0, **kwargs):
    """gets the chromaticity using several available methods

    method can be 'linopt', 'fft' or 'laskar'
    linopt: returns the chromaticity from the linopt function
    fft: tracks a single particle (one for x and one for y)
    and computes the tune from the fft
    harmonic: tracks a single particle (one for x and one for y)
    and computes the harmonic components

    see get_tune for kwargs inputs

    OUTPUT
        chromaticities = np.array([Q'x,Q'y])
    """

    dp_step = kwargs.pop('DPStep', DConstant.DPStep)
    if method == 'fft':
        print('Warning fft method not accurate to get the ' +
              'chromaticity')

    tune_up = get_tune(ring, method=method, dp=dp + 0.5 * dp_step, **kwargs)
    tune_down = get_tune(ring, method=method, dp=dp - 0.5 * dp_step, **kwargs)
    chrom = (tune_up - tune_down) / dp_step
    return numpy.array(chrom)


Lattice.linopt = linopt
Lattice.linopt2 = linopt2
Lattice.linopt4 = linopt4
Lattice.avlinopt = avlinopt
Lattice.get_mcf = get_mcf
Lattice.avlinopt = avlinopt
Lattice.get_tune = get_tune
Lattice.get_chrom = get_chrom
