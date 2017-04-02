import tensorflow as tf
import math
import numpy as np
import sys
from datetime import datetime
from prepare_data import read_train_data, build_dataset_from_raw

class CWS:
  def __init__(self):
    self.TAG_MAPS = np.array([[0, 1], [2, 3], [2, 3], [0, 1]], dtype=np.int32)

  def generate_batch(self,vocab_size, skip_window):
    """
    产生用于训练的数据
    :param vocab_size:
    :param skip_window:
    :return:
    """
    sentences, vocab_index, label_index, count, dictionary = read_train_data(
      vocab_size)
    words_batch = []
    label_batch = []
    window_length = 2 * skip_window + 1
    for i, sentence in enumerate(vocab_index):
      if len(sentence) > window_length:
        sentence_batch = []
        for j, _ in enumerate(vocab_index[i]):
          if j == 0:
            sentence_batch.append([0] + sentence[j:j + skip_window + 1])
          elif j == len(vocab_index[i]) - 1:
            sentence_batch.append(sentence[j - skip_window:j + 1] + [0])
          else:
            sentence_batch.append(sentence[j - skip_window:j + skip_window + 1])
        words_batch.append(sentence_batch)
        label_batch.append(label_index[i])

    return words_batch, label_batch


  def read_data(self,word_file_name, label_file_name, skip_window):
    word_file = open(word_file_name, 'r', encoding='utf-8')
    label_file = open(label_file_name, 'r', encoding='utf-8')
    words = word_file.read().splitlines()
    labels = label_file.read().splitlines()
    words_batch = []
    label_batch = []
    window_length = 2 * skip_window + 1

    for word in words:
      word_list = list(map(int, word.split(' ')))
      words_batch.append(np.array(word_list).reshape([len(word_list) // window_length, window_length]))
    for label in labels:
      label_batch.append(list(map(int, label.split(' '))))
    word_file.close()
    label_file.close()
    return np.array(words_batch), np.array(label_batch)


  def write_data(self,vocab_size, skip_window, word_file_name, label_file_name):
    words_batch, label_batch = self.generate_batch(vocab_size, skip_window)
    word_file = open(word_file_name, 'w', encoding='utf-8')
    label_file = open(label_file_name, 'w', encoding='utf-8')
    for index, word in enumerate(words_batch):
      word = np.array(word).reshape([3 * len(word)]).tolist()
      word_file.write(' '.join(map(str, word)) + '\n')
    for label in label_batch:
      label_file.write(' '.join(map(str, label)) + '\n')
    word_file.close()
    label_file.close()


  def train(self,vocab_size, embed_size, skip_window, word_file_name='word.txt',
            label_file_name='label.txt'):
    """
    用于训练模型
    :param vocab_size:
    :param embed_size:
    :param skip_window:
    :return:
    """
    tags = [0, 1, 2, 3]
    tags_count = len(tags)
    window_length = 2 * skip_window + 1
    concat_embed_size = embed_size * window_length
    graph = tf.Graph()
    words_batch, tags_batch = self.read_data(word_file_name, label_file_name, skip_window)
    print('start...')
    alpha = 0.02
    h = 300
    with graph.as_default():
      x = tf.placeholder(tf.float32, shape=[concat_embed_size, 1], name='x')
      embeddings = tf.Variable(tf.random_uniform([vocab_size, embed_size], -1.0, 1.0), name='embeddings')
      w2 = tf.Variable(tf.truncated_normal([h, concat_embed_size], stddev=1.0 / math.sqrt(concat_embed_size)),
                       name='w2')
      b2 = tf.Variable(tf.zeros([h, 1]), name='b2')

      w3 = tf.Variable(tf.truncated_normal([tags_count, h], stddev=1.0 / math.sqrt(concat_embed_size)), name='w3')
      b3 = tf.Variable(tf.zeros([tags_count, 1]), name='b3')

      word_score = tf.matmul(w3, tf.sigmoid(tf.matmul(w2, x) + b2)) + b3
      word_scores = tf.split(word_score, len(tags))
      # init_A = [[0.5,0.5,0,0],[1,0,0,0.15],[0,0,0.1,0],[1,0.01,0,0]]
      A = tf.Variable(
        [[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1], [1, 1, 0, 0]], dtype=tf.float32)

      param_list = [w2, w3, b2, b3]
      param_grad = [[0,0,0,0,0]] * 4
      for w_index, w in enumerate(word_scores):
        for p_index, p in enumerate(param_list):
          param_grad[w_index][p_index] = tf.gradients(w, p)
        param_grad[w_index][len(param_list)] = tf.gradients(w, x)

      saver = tf.train.Saver()

      with tf.Session(graph=graph) as sess:
        init = tf.global_variables_initializer()
        init.run()
        # 对每局句子进行参数更新
        for sentence_index, sentence in enumerate(words_batch):
          start = datetime.now().timestamp()
          print('s:' + str(sentence_index))

          sentence_embeds = tf.reshape(tf.nn.embedding_lookup(embeddings, sentence),
                                       [len(sentence), concat_embed_size, 1]).eval()
          sentence_scores = np.array(sess.run(word_score, feed_dict={x: sentence_embeds[0]}).T, dtype=np.float32)

          for embed in sentence_embeds[1:, :]:
            sentence_scores = np.append(sentence_scores, sess.run(word_score, feed_dict={x: embed}).T, 0)

          init_A_val = np.array(A.eval()[0])
          A_val = np.array(A.eval()[1:])
          current_tags = self.viterbi(sentence_scores, A_val, init_A_val)
          diff_tags = np.subtract(tags_batch[sentence_index], current_tags)

          for diff_index, diff_val in enumerate(diff_tags):
            if diff_val != 0:
              pos_grad_index = tags_batch[sentence_index][diff_index]
              neg_grad_index = current_tags[diff_index]
              for param_index, param in enumerate(param_list):
                self.update_param(param, param_grad[pos_grad_index][param_index], x, sentence_embeds[diff_index], alpha, 1,
                             sess)
                self.update_param(param, param_grad[neg_grad_index][param_index], x, sentence_embeds[diff_index], alpha, -1,
                             sess)

              start = datetime.now().timestamp()
              grad_x_pos_val = sess.run(param_grad[pos_grad_index][len(param_list)],
                                        feed_dict={x: sentence_embeds[diff_index]})
              grad_x_neg_val = sess.run(param_grad[neg_grad_index][len(param_list)],
                                        feed_dict={x: sentence_embeds[diff_index]})
              self.update_embeddings(embeddings, sentence[diff_index], alpha, 1, grad_x_pos_val[0], embed_size)
              self.update_embeddings(embeddings, sentence[diff_index], alpha, -1, grad_x_neg_val[0], embed_size)

              if diff_index == 0:
                tf.scatter_nd_add(A, [[0, tags_batch[sentence_index][diff_index]]], [alpha])
                tf.scatter_nd_add(A, [[0, current_tags[diff_index]]], [-alpha])
              else:
                before = tags_batch[sentence_index][diff_index - 1]
                tf.scatter_nd_add(A, [[before, tags_batch[sentence_index][diff_index]]], [alpha])
                tf.scatter_nd_add(A, [[current_tags[diff_index - 1], current_tags[diff_index]]], [-alpha])
          print(datetime.now().timestamp() - start)

        saver.save(sess, 'tmp/model.ckpt')


  def update_embeddings(self,embeddings, indices, alpha, delta_grad, val, embed_size):
    # start = datetime.now().timestamp()
    tf.scatter_nd_add(embeddings, np.expand_dims(indices, 1), (alpha * delta_grad * val).reshape(3, embed_size))
    # print(datetime.now().timestamp()-start)


  def update_param(self,param, grad, x, x_val, alpha, delta_grad, sess):
    # start = datetime.now().timestamp()
    grad_val = sess.run(grad, feed_dict={x: x_val})
    # print(datetime.now().timestamp() - start)
    # start = datetime.now().timestamp()
    tf.assign_add(param, alpha * delta_grad * grad_val[0])
    # print(datetime.now().timestamp() - start)


  def viterbi(self,emission, A, init_A):
    """
    维特比算法的实现，
    :param emission: 发射概率矩阵，对应于本模型中的分数矩阵
    :param A: 转移概率矩阵
    :return:
    """

    path = np.array([[0], [1]], dtype=np.int32)
    print(emission.shape)
    path_score = np.array([[init_A[0] + emission[0, 0]], [init_A[1] + emission[0, 1]]], dtype=np.float32)

    for line_index in range(1, emission.shape[0]):
      last_index = path[:, -1]
      cur_index = self.TAG_MAPS[last_index]  # 当前所有路径的可选的标记矩阵，2x2
      cur_res = A[last_index, cur_index] + emission[line_index, cur_index] + np.expand_dims(path_score[:, -1], 1)
      cur_max_index = np.argmax(cur_res, 1)
      path = np.insert(path, [path.shape[1]], np.expand_dims(np.choose(cur_max_index, cur_index.T), 1), 1)
      path_score = np.insert(path_score, [path_score.shape[1]], np.expand_dims(np.choose(cur_max_index, cur_res.T), 1), 1)

    return path[np.argmax(path_score[:, -1]), :]

  def seg(self,sentence):
    tags = [0, 1, 2, 3]
    tags_count = len(tags)
    window_length = 2 * skip_window + 1
    concat_embed_size = embed_size * window_length
    graph = tf.Graph()
    #words_batch, tags_batch = read_data(word_file_name, label_file_name, skip_window)
    #alpha = 0.02
    h = 300
    with graph.as_default():
      x = tf.placeholder(tf.float32, shape=[concat_embed_size, 1], name='x')
      embeddings = tf.Variable(tf.random_uniform([vocab_size, embed_size], -1.0, 1.0), name='embeddings')
      w2 = tf.Variable(tf.truncated_normal([h, concat_embed_size], stddev=1.0 / math.sqrt(concat_embed_size)),
                       name='w2')
      b2 = tf.Variable(tf.zeros([h, 1]), name='b2')
      w3 = tf.Variable(tf.truncated_normal([tags_count, h], stddev=1.0 / math.sqrt(concat_embed_size)), name='w3')
      b3 = tf.Variable(tf.zeros([tags_count, 1]), name='b3')
      word_score = tf.matmul(w3, tf.sigmoid(tf.matmul(w2, x) + b2)) + b3
      #word_scores = tf.split(word_score, len(tags))
      saver = tf.train.Saver()

      with tf.Session(graph=graph) as sess:
        saver.restore(sess,'/tmp/model.ckpt')
        data, count, dictionary = build_dataset_from_raw()




if __name__ == '__main__':
  vocab_size = 3500
  embed_size = 50
  skip_window = 1
  # sentences = open('sentences.txt').read().splitlines()
  # build_dataset(sentences,vocab_size)
  cws = CWS()
  cws.train(vocab_size, embed_size, skip_window)
  # write_data(vocab_size, skip_window, 'word.txt', 'label.txt')


