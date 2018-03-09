from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import tensorflow as tf
import numpy as np

import os
import sys
import time

import srgan_model as srgan

sys.path.append('../')
import image_utils as iu
from datasets import Div2KDataSet as DataSet


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

results = {
    'output': './gen_img/',
    'checkpoint': './model/checkpoint',
    'model': './model/SRGAN-model.ckpt'
}

train_step = {
    'train_epochs': 2000,
    'init_epochs': 100,
    'batch_size': 16,
    'logging_interval': 100,
}


def save_images(images, size, image_path):
    return iu.save_image(images, size, image_path)


def main():
    start_time = time.time()  # Clocking start

    # Div2K -  Track 1: Bicubic downscaling - x4 DataSet load
    ds = DataSet(mode='r')
    hr_lr_images = ds.images
    hr, lr = hr_lr_images[0],  hr_lr_images[1]

    print("[+] Loaded HR image ", hr.shape)
    print("[+] Loaded LR image ", lr.shape)

    # GPU configure
    gpu_config = tf.GPUOptions(allow_growth=True)
    config = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False, gpu_options=gpu_config)

    with tf.Session(config=config) as s:
        with tf.device("/gpu:1"):
            # SRGAN Model
            model = srgan.SRGAN(s, batch_size=train_step['batch_size'])

        # Initializing
        s.run(tf.global_variables_initializer())

        sample_x_hr, sample_x_lr = hr[:model.sample_num], lr[:model.sample_num]
        sample_x_hr, sample_x_lr = \
            np.reshape(sample_x_hr, [model.sample_num] + model.hr_image_shape[1:]),\
            np.reshape(sample_x_lr, [model.sample_num] + model.lr_image_shape[1:])

        # Export real image
        valid_image_height = model.sample_size
        valid_image_width = model.sample_size
        sample_hr_dir, sample_lr_dir = results['output'] + 'valid_hr.png', results['output'] + 'valid_lr.png'

        # Generated image save
        with tf.device("/cpu:0"):
            save_images(sample_x_hr, (valid_image_height, valid_image_width), sample_hr_dir)
            save_images(sample_x_lr, (valid_image_height, valid_image_width), sample_lr_dir)

        global_step = 0
        for epoch in range(train_step['train_epochs']):

            if epoch and epoch % model.lr_deacy_epoch == 0:
                lr_decay_rate = model.lr_decay_rate ** (epoch // model.lr_decay_epoch)

                # Update learning rate
                s.run(tf.assign(model.d_lr, model.d_lr * lr_decay_rate))
                s.run(tf.assign(model.g_lr, model.g_lr * lr_decay_rate))

            pointer = 0
            for i in range(ds.num_images // train_step['batch_size']):
                start = pointer
                pointer += train_step['batch_size']

                if pointer > ds.num_images:  # if 1 epoch is ended
                    # Shuffle training DataSet
                    perm = np.arange(ds.num_images)
                    np.random.shuffle(perm)

                    hr, lr = hr[perm], lr[perm]

                    start = 0
                    pointer = train_step['batch_size']

                end = pointer

                batch_x_hr, batch_x_lr = hr[start:end], lr[start:end]

                # reshape
                batch_x_hr = np.reshape(batch_x_hr, [train_step['batch_size']] + model.hr_image_shape[1:])
                batch_x_lr = np.reshape(batch_x_lr, [train_step['batch_size']] + model.lr_image_shape[1:])

                # Update Only G network
                d_loss, g_loss, g_init_loss = 0., 0., 0.
                if epoch <= train_step['init_epochs']:
                    _, g_init_loss = s.run([model.g_init_op, model.g_mse_loss],
                                           feed_dict={
                                               model.x_hr: batch_x_hr,
                                               model.x_lr: batch_x_lr,
                                           })
                # Update G/D network
                else:
                    _, d_loss, _, g_loss = s.run([model.d_op, model.d_loss, model.g_op, model.g_loss],
                                                 feed_dict={
                                                     model.x_hr: batch_x_hr,
                                                     model.x_lr: batch_x_lr,
                                                 })

                if i % train_step['logging_interval'] == 0:
                    summary = s.run(model.merged,
                                    feed_dict={
                                        model.x_hr: batch_x_hr,
                                        model.x_lr: batch_x_lr,
                                    })

                    # Print loss
                    if epoch <= train_step['init_epochs']:
                        print("[+] Step %08d => " % global_step,
                              " G init loss : {:.8f}".format(g_init_loss))
                    else:
                        print("[+] Step %08d => " % global_step,
                              " D loss : {:.8f}".format(d_loss),
                              " G loss : {:.8f}".format(g_loss))

                    # Training G model with sample image and noise
                    sample_x_lr = np.reshape(sample_x_lr, [model.sample_num] + model.lr_image_shape[1:])

                    samples = s.run(model.g,
                                    feed_dict={
                                        model.x_lr: sample_x_lr,
                                    })

                    samples = np.reshape(samples, [model.sample_size] + model.hr_image_shape[1:])

                    # Summary saver
                    model.writer.add_summary(summary, global_step)

                    # Export image generated by model G
                    sample_image_height = model.output_height
                    sample_image_width = model.output_width
                    sample_dir = results['output'] + 'train_{:08d}.png'.format(global_step)

                    # Generated image save
                    with tf.device("/cpu:1"):
                        save_images(samples, (sample_image_height, sample_image_width), sample_dir)

                    # Model save
                    model.saver.save(s, results['model'], global_step=global_step)

                global_step += 1

    end_time = time.time() - start_time  # Clocking end

    # Elapsed time
    print("[+] Elapsed time {:.8f}s".format(end_time))

    # Close tf.Session
    s.close()


if __name__ == '__main__':
    main()
