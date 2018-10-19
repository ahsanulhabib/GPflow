import tensorflow as tf

from . import dispatch
from .. import kernels
from .. import mean_functions as mfn
from ..features import InducingPoints
from ..util import NoneType
from .expectations import expectation
from .probability_distributions import (DiagonalGaussian, Gaussian,
                                        MarkovGaussian)


@dispatch.expectation.register(Gaussian, kernels.Linear, NoneType, NoneType, NoneType)
def _E(p, kern, _, __, ___, nghp=None):
    """
    Compute the expectation:
    <diag(K_{X, X})>_p(X)
        - K_{.,.} :: Linear kernel

    :return: N
    """
    # use only active dimensions
    Xmu, _ = kern.slice(p.mu, None)
    Xcov = kern.slice_cov(p.cov)

    return tf.reduce_sum(kern.variance * (tf.matrix_diag_part(Xcov) + Xmu ** 2), 1)


@dispatch.expectation.register(Gaussian, kernels.Linear, InducingPoints, NoneType, NoneType)
def _E(p, kern, feat, _, __, nghp=None):
    """
    Compute the expectation:
    <K_{X, Z}>_p(X)
        - K_{.,.} :: Linear kernel

    :return: NxM
    """
    # use only active dimensions
    Z, Xmu = kern.slice(feat.Z, p.mu)

    return tf.matmul(Xmu, Z * kern.variance, transpose_b=True)


@dispatch.expectation.register(
        Gaussian, kernels.Linear, InducingPoints, mfn.Identity, NoneType)
def _E(p, kern, feat, mean, _, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <K_{Z, x_n} x_n^T>_p(x_n)
        - K_{.,.} :: Linear kernel

    :return: NxMxD
    """
    Xmu, Xcov = p.mu, p.cov

    # TODO(@awav):
    # with tf.control_dependencies([tf.assert_equal(
    #         tf.shape(Xmu)[1], tf.constant(kern.input_dim, settings.tf_int),
    #         message="Currently cannot handle slicing in exKxz.")]):
    #     Xmu = tf.identity(Xmu)

    N = tf.shape(Xmu)[0]
    var_Z = kern.variance * feat.Z  # MxD
    tiled_Z = tf.tile(tf.expand_dims(var_Z, 0), (N, 1, 1))  # NxMxD
    return tf.matmul(tiled_Z, Xcov + (Xmu[..., None] * Xmu[:, None, :]))


@dispatch.expectation.register(
        MarkovGaussian, kernels.Linear, InducingPoints, mfn.Identity, NoneType)
def _E(p, kern, feat, mean, _, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <K_{Z, x_n} x_{n+1}^T>_p(x_{n:n+1})
        - K_{.,.} :: Linear kernel
        - p       :: MarkovGaussian distribution (p.cov 2x(N+1)xDxD)

    :return: NxMxD
    """
    Xmu, Xcov = p.mu, p.cov

    # TODO(@awav):
    # with tf.control_dependencies([tf.assert_equal(
    #         tf.shape(Xmu)[1], tf.constant(kern.input_dim, settings.tf_int),
    #         message="Currently cannot handle slicing in exKxz.")]):
    #     Xmu = tf.identity(Xmu)

    N = tf.shape(Xmu)[0] - 1
    var_Z = kern.variance * feat.Z  # MxD
    tiled_Z = tf.tile(tf.expand_dims(var_Z, 0), (N, 1, 1))  # NxMxD
    eXX = Xcov[1, :-1] + (Xmu[:-1][..., None] * Xmu[1:][:, None, :])  # NxDxD
    return tf.matmul(tiled_Z, eXX)


@dispatch.expectation.register(
        (Gaussian, DiagonalGaussian),
        kernels.Linear, InducingPoints, kernels.Linear, InducingPoints)
def _E(p, kern1, feat1, kern2, feat2, nghp=None):
    """
    Compute the expectation:
    expectation[n] = <Ka_{Z1, x_n} Kb_{x_n, Z2}>_p(x_n)
        - Ka_{.,.}, Kb_{.,.} :: Linear kernels
    Ka and Kb as well as Z1 and Z2 can differ from each other, but this is supported
    only if the Gaussian p is Diagonal (p.cov NxD) and Ka, Kb have disjoint active_dims
    in which case the joint expectations simplify into a product of expectations

    :return: NxMxM
    """
    if kern1.on_separate_dims(kern2) and isinstance(p, DiagonalGaussian):  # no joint expectations required
        eKxz1 = expectation(p, (kern1, feat1))
        eKxz2 = expectation(p, (kern2, feat2))
        return eKxz1[:, :, None] * eKxz2[:, None, :]

    if kern1 != kern2 or feat1 != feat2:
        raise NotImplementedError("The expectation over two kernels has only an "
                                  "analytical implementation if both kernels are equal.")

    kern = kern1
    feat = feat1

    # use only active dimensions
    Xcov = kern.slice_cov(tf.matrix_diag(p.cov) if isinstance(p, DiagonalGaussian) else p.cov)
    Z, Xmu = kern.slice(feat.Z, p.mu)

    N = tf.shape(Xmu)[0]
    var_Z = kern.variance * Z
    tiled_Z = tf.tile(tf.expand_dims(var_Z, 0), (N, 1, 1))  # NxMxD
    XX = Xcov + tf.expand_dims(Xmu, 1) * tf.expand_dims(Xmu, 2)  # NxDxD
    return tf.matmul(tf.matmul(tiled_Z, XX), tiled_Z, transpose_b=True)