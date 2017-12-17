import tensorflow as tf 
import numpy as np
import time
import os
import sys
import re
from datetime import datetime

from modules import *
from utils import Dataset

class Model(object):

   def __init__(self, opts, is_training):
      """Initialize the model

      Args:
         opts: All the hyper-parameters of the network
         is_training: Boolean which indicates whether the model is in train
            mode or test mode
      """
      self.opts = opts
      self.h = opts.h
      self.w = opts.w
      self.c = opts.c
      self.sess = tf.Session()
      self.should_train = is_training
      self.init = tf.global_variables_initializer()
      # self.saver = tf.train.Saver(write_version=tf.train.SaverDef.V2)
      self.build_graph()

   def build_graph(self):
      """Generate various parts of the graph
      """
      self.non_lin = {'relu' : lambda x: relu(x, name='relu'),
                      'lrelu': lambda x: lrelu(x, name='lrelu'),
                      'tanh' : lambda x: tanh(x, name='tanh')
                     }
      self.placeholders()
      self.E  = self.encoder(self.target_images, self.opts.e_layers,
         self.opts.e_kernels, self.opts.e_nonlin)
      self.G  = self.generator(self.input_images, self.code, self.opts.g_layers,
         self.opts.g_kernels, self.opts.g_nonlin)
      # self.D  = self.discriminator(self.input_images, reuse=False)
      # self.D_ = self.discriminator(self.G, reuse=True)
      self.summaries()

   def placeholders(self):
      """Allocate placeholders of the graph
      """
      self.input_images = tf.placeholder(tf.float32, [None, self.h, self.w, self.c], name="input_images")
      self.target_images = tf.placeholder(tf.float32, [None, self.h, self.w, self.c], name="target_images")
      self.code = tf.placeholder(tf.float32, [None, self.h, self.w, self.opts.code_len], name="code")
      self.is_training = tf.placeholder(tf.bool, name="is_training")

   def summaries(self):
      """Adds all the necessary summaries
      """
      in_images = tf.summary.image('Input_images', self.input_images, max_outputs=10)
      tr_images = tf.summary.image('Target_images', self.target_images, max_outputs=10)
      gen_images = tf.summary.image('Gen_images', self.G, max_outputs=10)
      self.summaries = tf.summary.merge_all()

   def encoder(self, image, num_layers=3, kernels=64, non_lin='relu'):
      """Encoder which generates the latent code
      
      Args:
         image: Image which is to be encoded

      Returns:
         The encoded latent code
      """
      self.e_layers = {}
      with tf.variable_scope('encoder'):
         if self.opts.e_type == "normal":
            return self.normal_encoder(image, num_layers=num_layers, output_neurons=8,
               kernels=kernels, non_lin=non_lin)
         elif self.opts.e_type == "residual":
            return self.resnet_encoder(image, num_layers, output_neurons=8,
               kernels=kernels, non_lin=non_lin)
         else:
            raise ValueError("No such type of encoder exists!")

   def normal_encoder(self, image, num_layers=4, output_neurons=1, kernels=64, non_lin='relu'):
      """Few convolutional layers followed by downsampling layers
      """
      k, s = 4, 2
      try:
         self.e_layers['conv0'] = conv2d(image, kernel=k, out_channels=kernels*1, stride=s, name='conv0',
            non_lin=self.non_lin[non_lin])
      except KeyError:
         raise KeyError("No such non-linearity is available!")
      for idx in range(1, num_layers):
         input_layer = self.e_layers['conv{}'.format(idx-1)]
         factor = min(2**idx, 4)
         try:
            self.e_layers['conv{}'.format(idx)] = conv2d(input_layer, kernel=k,
               out_channels=kernels*factor, stride=s, name='conv{}'.format(idx),
               non_lin=self.non_lin[non_lin]) 
         except KeyError:
            raise KeyError("No such non-linearity is available!")
      self.e_layers['pool'] = average_pool(self.e_layers['conv{}'.format(num_layers-1)],
         ksize=8, strides=8, name='pool')
      units = int(np.prod(self.e_layers['pool'].get_shape().as_list()[1:]))
      reshape_layer = tf.reshape(self.e_layers['pool'], [-1, units])
      self.e_layers['full'] = fully_connected(reshape_layer, output_neurons, name='full')
      return self.e_layers['full']

   def resnet_encoder(self, image, num_layers=4, output_neurons=1, kernels=64, non_linearity='relu'):
      """Residual Network with several residual blocks
      """
      raise NotImplementedError("Not Implemented")

   def generator(self, image, z, layers=3, kernel=64, non_lin='relu'):
      """Generator graph of GAN

      Args:
         image  : Conditioned image on which the generator generates the image 
         z      : Latent space code
         layers : The number of layers either in downsampling / upsampling 
         kernel : Number of kernels to the first layer of the network
         non_lin: Non linearity to be used

      Returns:
         Generated image
      """
      self.g_layers = {}
      with tf.variable_scope('generator'):
         if self.opts.where_add == "input":
            return self.generator_input(image, z, layers, kernel, non_lin)
         elif self.opts.where_add == "all":
            return self.generator_all(image, z, layers, kernel, non_lin)
         else:
            raise ValueError("No such type of generator exists!")

   def generator_input(self, image, z, layers=3, kernel=64, non_lin='lrelu'):
      """Generator graph where noise is concatenated to the first layer

      Args:
         image : Conditioned image on which the generator generates the image
         z     : Latent space noise
         layers: The number of layers either in downsampling / upsampling 
         kernel: Number of kernels to the first layer of the network

      Returns:
         Generated image
      """
      in_channels = self.opts.c + self.opts.code_len
      z = z # TODO : Transform z into tensor of shape: [self.opts.h, self.opts.w, self.opts.code_len]
      in_layer = image + z
      k, s = 4, 2
      factor = 1
      # Downsampling
      for idx in xrange(layers):
         factor = min(2**idx, 4)
         try:
            self.g_layers['conv{}'.format(idx)] = conv2d(in_layer, kernel=k, 
               out_channels=kernel*factor, stride=s, name='conv{}'.format(idx),
               non_lin=self.non_lin[non_lin])
         except KeyError:
            raise KeyError("No such non-linearity is available!")
         # Maybe add Pooling layer ?            
         in_layer = self.g_layers['conv{}'.format(idx)]

      # Upsampling
      in_layer = self.g_layers['conv{}'.format(layers-1)]
      new_idx = layers
      for idx in xrange(layers-2, -1, -1):
         out_shape = self.g_layers['conv{}'.format(idx)].get_shape().as_list()[1]
         out_channels = self.g_layers['conv{}'.format(idx)].get_shape().as_list()[-1]
         try:
            self.g_layers['conv{}'.format(new_idx)] = deconv(in_layer, kernel=k,
               out_shape=out_shape, out_channels=out_channels, name='deconv{}'.format(new_idx),
               non_lin=self.non_lin[non_lin])
         except KeyError:
            raise KeyError("No such non-linearity is available!")
         input_layer = self.g_layers['conv{}'.format(new_idx)]
         self.g_layers['conv{}'.format(new_idx)] = add_layers(input_layer, self.g_layers['conv{}'.format(idx)])
         in_layer = self.g_layers['conv{}'.format(new_idx)]
         new_idx += 1
      self.g_layers['conv{}'.format(layers*2-1)] = deconv(self.g_layers['conv{}'.format(new_idx-1)],
         kernel=k, out_shape=self.h, out_channels=3, name='deconv{}'.format(new_idx), non_lin=self.non_lin['tanh'])
      return self.g_layers['conv{}'.format(new_idx)]

   def generator_all(self, image, z, layers=3, kernel=64, non_lin='lrelu'):
      """Generator graph where noise is to all the layers

      Args:
         image : Conditioned image on which the generator generates the image
         z     : Latent space noise
         layers: The number of layers either in downsampling / upsampling 

      Returns:
         Generated image
      """
      raise NotImplementedError("Not Implemented")


   def discriminator(self, conditioning_image, image, reuse=False):
      """Discriminator graph of GAN
      The discriminator is a PatchGAN discriminator which consists of two 
         discriminators for two different scales i.e, 70x70 and 140x140
      Authors claim not conditioning the discriminator yields better results
         and hence not conditioning the discriminator with the input image
      Authors also claim that using two discriminators for cVAE-GAN and cLR-GAN
         yields better results, here we share the weights for both of them

      Args:
         image: Input image to the discriminator
         reuse: Flag to check whether to reuse the variables created for the
            discriminator graph

      Returns:
         Whether or not the input image is real or fake
      """
      with tf.name_scope('discriminator'):
         pass

   def discriminator_70x70(self, conditioning_image, image, resuse=False):
      """70x70 PatchGAN discriminator
      """

   def discriminator_140x140(self, conditioning_image, image, resuse=False):
      """140x140 PatchGAN discriminator
      """

   def loss(self, z1, z2, p1, p2):
      """Implements the loss graph
      """

      def gan_loss():
         """Implements the GAN loss
         """
         pass

      def l1_loss(z1, z2):
         """Implements L1 loss graph
         
         Args:
            z1: Image in case of cVAE-GAN
                Vector in case of cLR-GAN
            z2: Image in case of cVAE-GAN
                Vector in case of cLR-GAN

         Returns:
            L1 loss
         """
         pass

      def kl_divergence(p1, p2):
         """Apply KL divergence
         
         Args:
            p1: 1st probability distribution
            p2: 2nd probability distribution

         Returns:
            KL Divergence between the given distributions
         """
         pass

      with tf.name_scope('loss'):
         l1_loss_ = l1_loss(z1, z2)
         kl_loss_ = kl_divergence(p1, p2)
         gan_loss = gan_loss()

   def train(self):
      """Train the network
      """
      pass

   def checkpoint(self, iteration):
      """Creates a checkpoint at the given iteration

      Args:
         iteration: Iteration number of the training process
      """
      self.saver.save(self.sess, os.path.join(self.opts.summary_dir, "model_{}.ckpt").format(iteration))

   def test_graph(self):
      """Generate the graph and check if the connections are correct
      """
      print 'Testing the architecture of the graph of the network...'
      self.writer = tf.summary.FileWriter(self.opts.summary_dir, self.sess.graph)


   def test(self, image):
      """Test the model

      Args:
         image: Input image to the model

      Returns:
         The generated image conditioned on the input image
      """
      if image == '':
         raise ValueError('Specify the path to the test image')
      latest_ckpt = tf.train.latest_checkpoint(self.opts.ckpt)
      tf.saver.restore(self.sess, latest_ckpt)
