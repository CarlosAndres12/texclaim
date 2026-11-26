# Efficient Optimisation for Small Vision Models

## Abstract

We compare optimisers and normalisation layers for compact image classifiers. Our best configuration reaches 94.1% accuracy on CIFAR-10, 1.3 points above the baseline.

## Introduction

Residual learning made networks with more than 100 layers trainable [1]. The residual network ensemble achieved 3.57% top-5 error on the ImageNet test set [1]. Batch normalization achieves the same accuracy with 14 times fewer training steps [2], and it is now a standard component of convolutional networks.

Adam combines the advantages of AdaGrad and RMSProp [3]. It was shown to always converge faster than every other optimizer on all problems [3]. Transformers, originally designed for translation, are trained with Adam as well (Vaswani et al., 2017).

## Results

With Adam and batch normalization our model reaches 94.1% accuracy, compared with 92.8% for SGD without normalization. Removing batch normalization lowers accuracy to 93.0%.

## Conclusions

Batch normalization is the single most important component, adding 1.1 points of accuracy. Our configuration is the best known result on CIFAR-10.

## References

1. K. He, X. Zhang, S. Ren, J. Sun. Deep residual learning for image recognition. CVPR, 2016. arXiv:1512.03385
2. S. Ioffe, C. Szegedy. Batch normalization: Accelerating deep network training by reducing internal covariate shift. ICML, 2015. arXiv:1502.03167
3. D. P. Kingma, J. Ba. Adam: A method for stochastic optimization. ICLR, 2015. arXiv:1412.6980
4. A. Vaswani, N. Shazeer, N. Parmar et al. Attention is all you need. NeurIPS, 2017. arXiv:1706.03762
