from functools import partial
import pickle
import pandas as pd
import numpy as np
from keras.preprocessing.sequence import pad_sequences
from keras.models import Model, load_model
from keras.layers import Input, LSTM, Dense, Masking
import matplotlib
import matplotlib.pyplot as plt
from keras.callbacks import ModelCheckpoint
from keras_metrics import KerasMetrics
from keras.optimizers import adam
import keras.backend as K
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedKFold
from scipy.spatial import distance
opt = adam()

with open('Files/phones.pickle', 'rb') as file:
    phones = pickle.load(file)

    
def features():
    """
    Return the list of phone features used.
    
    Returns:
    --------    
    features : list
    """
    features = ['oclusiva', 'nasal', 'tepe', 'fricativa', 'l-aprox', 'bilabial', 'labiodental',
               'alveolar', 'p-alveolar', 'palatal', 'velar', 'glotal', 'vozeada', 'fechada',
               'm-fechada', 'm-aberta', 'aberta', 'anterior', 'posterior', 'beg', 'end']
    return features


def code(phone):
    """
    Create array of features for a single phone.
    
    Parameters:
    -----------
    phone : str
    
    Returns:
    --------
    array e.g. [0.0, 1.0, 0.0, ...]
    """
    array = []
    fts = features()
    for item in fts:
        if item in phones[phone]:
            array.append(1)
        else:
            array.append(0)
    return np.array(array)


def code_verb(verb):
    """
    Build up a matrix composed of featurized vectors for each phone in a verb.
    
    Parameters:
    -----------
    verb : str
    
    Return:
    -------
    array 
    """
    coded = list()
    for item in verb:
        coded.append(code(item))
    return np.array(coded)


def verify(verb):
    """
    Test for each phone in a verb if this phone is in the dictionary of phones.
    (Used to test new corpus)
    
    Parameters:
    -----------
    verb: str
    
    Return:
    -------
    None (print the phone that is not listed in the dictionary of valid phones)
    """
    for phone in verb:
        if phone not in phones.keys():
            print(phone, verb)

            
def preprocessing(corpus):
    """
    Pre process corpus for vector representations.
    
    Parameters:
    ----------   
    corpus : pandas df
    
    Returns:
    -------
    coded_in : array
    coded_out : array
    padded_in : array
    padded_out : array
    padded_out_target : array
    """
    coded_in = corpus.iloc[:,0].apply(code_verb)
    coded_out = corpus.iloc[:,1].apply(code_verb)
    coded_out_target = coded_out.apply(lambda x: np.vstack((x[1:],np.zeros(21))))
    padded_in = pad_sequences(coded_in, value=np.zeros(21))
    padded_out = pad_sequences(coded_out, value=np.zeros(21),padding="post")
    padded_out_target = pad_sequences(coded_out_target, value=np.zeros(21),padding="post")
    omega = 2*padded_out.mean(axis=0).mean(axis=0) + 0.001
        
    return coded_in, coded_out, padded_in, padded_out, padded_out_target, omega

def find_closest_array(predicted):
    """
    Find closest array.
    
    Parameters:
    ----------   
    predicted : type array
    
    Returns:
    -------
    candidate : type string
    """
    import pickle
    
    min_dst = 10000
    candidate = ''
     
    with open('Files/phone_arrays.pickle', 'rb') as file:
        phone_arrays = pickle.load(file)
    for phone in phone_arrays:
        dst = distance.euclidean(predicted, phone_arrays[phone])
        # finds the minimum distance first
        if dst < min_dst:
            min_dst = dst
            candidate = phone
    return candidate


def decode_sequence(input_seq, encoder, decoder, omega, renormalize):
    """
    Decode a whole sequence of predicted vectors of features into a verb.
    
    Parameters:
    -----------
    input_seq : array
    encoder : keras model
    decoder : keras model
    renormalize : bool
    
    Returns:
    --------
    fts : array of features (still not being used)
    decoded_verb : str
    """
    import pickle
    with open('Files/lookup.pickle', 'rb') as file:
        lookup = pickle.load(file)
    # Encode the input as state vectors.
    states_value = encoder.predict(input_seq)

    # Generate empty target sequence of length 1.
    #target_seq = np.zeros((1, 1, 21)) # max decoder len = 13, 21 features 03/04
    max_decoder_seq_length = 13
    
    #Populate the first character of target sequence with the start character.
    target_seq= lookup['#'].reshape(1, 1, -1)

    # Sampling loop for a batch of sequences
    # (to simplify, here we assume a batch of size 1).
    stop_condition = False
    decoded_verb = ''
    fts = []
    while not stop_condition:
        output_phones, h, c = decoder.predict(
            [target_seq] + states_value)
        fts.append(output_phones)
        
        # Sample a phone
        if renormalize:
            sampled_phone = find_closest_array(output_phones[0, -1, :]/omega)
        else:
            sampled_phone = find_closest_array(output_phones[0, -1, :])                                               
        sampled_phone_vector = lookup[sampled_phone]
        decoded_verb += sampled_phone
        # Exit condition: either hit max length
        # or find stop character.
        if (sampled_phone == '#' or 
           len(decoded_verb) > max_decoder_seq_length):
            stop_condition = True

        # Update the target sequence (of length 1).
        target_seq = sampled_phone_vector.reshape(1, 1, -1)

        # Update states
        states_value = [h, c]

    return fts, decoded_verb[:-1]


def decode_sequences(seq, encoder, decoder, omega, renormalize):
    """
    Decode a batch of predicted vectors of features into a verb.
    
    Parameters:
    -----------
    seq : array
    encoder : keras model
    decoder : keras model
    renormalize : bool
    
    Returns:
    --------
    fts : array of features (still not being used)
    decoded_verb : str
    """
    if len(seq.shape) == 3:
        return zip(*[decode_sequence(s.reshape(1,*s.shape), encoder, decoder,omega, renormalize) for s in seq])
    else:  
        fts, decoded_verb = decode_sequence(seq.reshape(1,*seq.shape), encoder, decoder, omega, renormalize) 
    return fts, decoded_verb

    
    
def decode_from_df_and_models(df, encoder, decoder, renormalize):
    """
    Decode everything directly from a corpus. Returns a new df comparing predicted with expected values.
    
    Parameters:
    -----------
    df : pandas df
    encoder : keras model
    decoder : keras model
    renormalize : bool
    
    Returns:
    --------
    res : pandas df
    """
    coded_in, coded_out, padded_in, padded_out, padded_out_target, omega = preprocessing(df)
    fts, decoded_seqs = decode_sequences(padded_in, encoder, decoder, omega, renormalize) 
    res = pd.DataFrame(decoded_seqs, index=df.iloc[:,0].tolist()).reset_index()
    res.columns = ['v_inf', 'predicted']
    res = pd.merge(res, df, on='v_inf', how='inner')
    res.columns = ['infinitive', 'predicted', 'target', 'class']
    res['target'] = res.target.str.strip('#')
    res['target'] = res.target.str.strip('$')
    return  res
    #return fts 03/04

def train(data, epochs, length=None, verbose=False, latent_dim=256, NUM_ENCODER_TOKENS=21):
    """
   Train the encoder decoder model.
    
    Parameters:
    -----------
    data : pandas df
    epochs : int
    length : int (can be used for learning curve)
    verbose : bool
    latent_dim : int
    NUM_ENCODER_TOKENS : int (cant be changed)
    
    Returns:
    --------
    model : keras model
    decoder_from_df : function with pre parametrized encoder and decoder
    history : list (obtained from fit)
    """
    coded_in, coded_out, padded_in, padded_out, padded_out_target, omega = preprocessing(data)
    if length==None: length=len(padded_in)
        
    # Define an input sequence and process it.
    encoder_inputs = Input(shape=(None, NUM_ENCODER_TOKENS)) #19
    #encoder_inputs = Masking()(encoder_inputs) # Assuming PAD is zeros
    encoder = LSTM(latent_dim, return_state=True)
    # Now the LSTM will ignore the PADs when encoding
    # by skipping those timesteps that are masked
    encoder_outputs, state_h, state_c = encoder(encoder_inputs)
    # We discard `encoder_outputs` and only keep the states.
    encoder_states = [state_h, state_c]

    # Set up the decoder, using `encoder_states` as initial state.
    num_decoder_tokens = 21
    decoder_inputs = Input(shape=(None, num_decoder_tokens))
    # We set up our decoder to return full output sequences,
    # and to return internal states as well. We don't use the
    # return states in the training model, but we will use them in inference.
    decoder_lstm = LSTM(latent_dim, return_sequences=True, return_state=True)
    decoder_outputs, _, _ = decoder_lstm(decoder_inputs,
                             initial_state=encoder_states)
    decoder_dense = Dense(num_decoder_tokens, activation='sigmoid')
    decoder_outputs = decoder_dense(decoder_outputs)

    # Define the model that will turn
    # `encoder_input_data` & `decoder_input_data` into `decoder_target_data`
    model = Model([encoder_inputs, decoder_inputs], decoder_outputs)
      
    encoder_model = Model(encoder_inputs, encoder_states)
    
    decoder_state_input_h = Input(shape=(latent_dim,))
    decoder_state_input_c = Input(shape=(latent_dim,))
    decoder_states_inputs = [decoder_state_input_h, decoder_state_input_c]
    decoder_outputs, state_h, state_c = decoder_lstm(
        decoder_inputs, initial_state=decoder_states_inputs)
    decoder_states = [state_h, state_c]
    decoder_outputs = decoder_dense(decoder_outputs)
    decoder_model = Model(
        [decoder_inputs] + decoder_states_inputs,
        [decoder_outputs] + decoder_states)
    
    decoder_from_df = partial(decode_from_df_and_models, encoder=encoder_model, decoder=decoder_model)

    keras_metrics = KerasMetrics()
    model.compile(optimizer=opt, loss='binary_crossentropy', metrics=[ keras_metrics.fbeta_score,
                   keras_metrics.recall,
                   keras_metrics.precision]) 
    
    history = model.fit([padded_in[:length], padded_out[:length]],
                        padded_out_target[:length],
                        batch_size=128,
                        epochs=epochs,
                        validation_split=0.2,verbose=verbose)
        
    return model, decoder_from_df, history


def plot(history, score):
    """
    Plot training history.
    
    Parameters:
    -----------
    history : keras list (from fit)
    score : fbeta_score, precision, recall or loss
    """
    plt.plot(history.history[score])
    plt.plot(pd.Series(history.history['val_{}'.format(score)]))
    plt.title('model {}'.format(score))
    plt.ylabel(score)
    plt.xlabel('epoch')
    plt.legend(['train', 'test'], loc='upper left');       

def plot_results(history):
    plt.figure(figsize=(16, 4))
    plt.subplot(1,4,1)
    plot(history, 'fbeta_score')

    plt.subplot(1,4,2)
    plot(history, 'precision')

    plt.subplot(1,4,3)
    plot(history, 'recall')

    plt.subplot(1,4,4)
    plot(history, 'loss')
    

def kfold(corpus, n, renorm=False):
    cv = StratifiedKFold(n)

    all_decodings = pd.DataFrame()
    for i_train, i_test in cv.split(corpus, y=corpus['class']):
        corpus_train, corpus_test = corpus.iloc[i_train], corpus.iloc[i_test]
        print(corpus_train.shape, corpus_test.shape)

        model, decoder,  _ = train(corpus_train, epochs=300)
        decoded = decoder(corpus_test, renormalize=renorm)

        all_decodings = all_decodings.append(decoded)
        
    return all_decodings