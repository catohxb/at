from .constants import e_mass, p_mass
import numpy


class Particle(object):
    """Particle object

    This object defines the properties of the particles circulating in a ring

    Particle(name, **params)

    PARAMETERS
        name        Particle name. 'electron', 'positron and 'proton' are
                    predefined. For other particles, the rest energy and charge
                    must be provided as keywords.

    KEYWORDS
        rest_energy Particle rest energy [ev]
        charge      Particle charge [elementary charge]
        *           Other keywords will be set as attributes of the particle
    """
    _known = dict(
        relativistic=dict(rest_energy=0.0, charge=-1.0),
        electron=dict(rest_energy=e_mass, charge=-1.0),
        positron=dict(rest_energy=e_mass, charge=1.0),
        proton=dict(rest_energy=p_mass, charge=1.0)
    )

    def __init__(self, name, **kwargs):
        if name != 'relativistic':
            raise NotImplementedError(
                "Only 'relativistic' is allowed at the moment")
        if name in self._known:
            kwargs.update(self._known[name])
        self.name = name
        # Use a numpy scalar to allow division by zero
        self._rest_energy = numpy.array(kwargs.pop('rest_energy'), dtype=float)
        self._charge = kwargs.pop('charge')
        for (key, val) in kwargs.items():
            setattr(self, key, val)

    def __repr__(self):
        if self.name in self._known:
            return "Particle('{0}')".format(self.name)
        else:
            attrs = vars(self).copy()
            name = attrs.pop('name')
            attrs['rest_energy'] = attrs.pop('_rest_energy')
            attrs['charge'] = attrs.pop('_charge')
            args = ', '.join('{0}={1!r}'.format(k, v) for k, v in attrs.items())
            return "Particle('{0}', {1})".format(name, args)

    def __str__(self):
        if self.name in self._known:
            return self.name
        else:
            return self.__repr__()

    # Use properties so that they are read-only
    @property
    def rest_energy(self):
        return self._rest_energy

    @property
    def charge(self):
        return self._charge
