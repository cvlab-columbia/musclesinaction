'''
Entire training pipeline logic.
'''

import torch
import torch.nn as nn
import pdb
import torch.nn.functional as F
import time
# Internal imports.
import musclesinaction.losses.loss as loss
import musclesinaction.utils.utils as utils


class MyTrainPipeline(torch.nn.Module):
    '''
    Wrapper around most of the training iteration such that DataParallel can be leveraged.
    '''

    def __init__(self, train_args, logger, networks, device):
        super().__init__()
        self.train_args = train_args
        self.logger = logger
        self.networks = torch.nn.ModuleList(networks)
        self.my_model = networks[0]
        self.device = device
        self.phase = None  # Assigned only by set_phase().
        self.losses = None  # Instantiated only by set_phase().
        self.crossent = nn.CrossEntropyLoss()
        self.mse = nn.MSELoss()
        

    def set_phase(self, phase):
        self.phase = phase
        self.losses = loss.MyLosses(self.train_args, self.logger, phase)

        if phase == 'train':
            self.train()
            for net in self.networks:
                if net is not None:
                    net.train()
            torch.set_grad_enabled(True)

        else:
            self.eval()
            for net in self.networks:
                if net is not None:
                    net.eval()
            torch.set_grad_enabled(False)

    def perspective_projection(self, points, rotation, translation,
                            focal_length, camera_center):

        batch_size = points.shape[0]
        K = torch.zeros([batch_size, 3, 3], device=points.device)
        K[:,0,0] = focal_length
        K[:,1,1] = focal_length
        K[:,2,2] = 1.
        K[:,:-1, -1] = camera_center

        # Transform points
        #pdb.set_trace()
        points = torch.einsum('bij,bkj->bki', rotation, points)
        points = points + translation.unsqueeze(1)

        # Apply perspective distortion
        projected_points = points / points[:,:,-1].unsqueeze(-1)

        # Apply camera intrinsics
        projected_points = torch.einsum('bij,bkj->bki', K, projected_points)

        return projected_points[:, :, :-1], points

    def convert_pare_to_full_img_cam(
            self, pare_cam, bbox_height, bbox_center,
            img_w, img_h, focal_length, crop_res=224):
        # Converts weak perspective camera estimated by PARE in
        # bbox coords to perspective camera in full image coordinates
        # from https://arxiv.org/pdf/2009.06549.pdf
        s, tx, ty = pare_cam[:, 0], pare_cam[:, 1], pare_cam[:, 2]
        res = 224
        r = bbox_height / res
        tz = 2 * focal_length / (r * res * s)
        #pdb.set_trace()
        cx = 2 * (bbox_center[:, 0] - (img_w / 2.)) / (s * bbox_height)
        cy = 2 * (bbox_center[:, 1] - (img_h / 2.)) / (s * bbox_height)

        cam_t = torch.stack([tx + cx, ty + cy, tz], dim=-1)

        return cam_t

    def forward(self, data_retval, cur_step, total_step):
        '''
        Handles one parallel iteration of the training or validation phase.
        Executes the models and calculates the per-example losses.
        This is all done in a parallelized manner to minimize unnecessary communication.
        :param data_retval (dict): Data loader elements.
        :param cur_step (int): Current data loader index.
        :param total_step (int): Cumulative data loader index, including all previous epochs.
        :return (model_retval, loss_retval)
            model_retval (dict): All output information.
            loss_retval (dict): Preliminary loss information (per-example, but not batch-wide).
        '''
        cur = time.time()
        twodskeleton = data_retval['2dskeleton']
        twodskeleton = twodskeleton.reshape(twodskeleton.shape[0],twodskeleton.shape[1],-1)


        threedskeleton = data_retval['3dskeleton']
        bboxes = data_retval['bboxes']
        predcam = data_retval['predcam']
        proj = 5000.0
        
        height= bboxes[:,:,2:3].reshape(bboxes.shape[0]*bboxes.shape[1])
        center = bboxes[:,:,:2].reshape(bboxes.shape[0]*bboxes.shape[1],-1)
        focal=torch.tensor([[proj]]).to(self.device).repeat(height.shape[0],1)
        predcamelong = predcam.reshape(predcam.shape[0]*predcam.shape[1],-1)
        translation = self.convert_pare_to_full_img_cam(predcamelong,height,center,1080,1920,focal[:,0])
        reshapethreed= threedskeleton.reshape(threedskeleton.shape[0]*threedskeleton.shape[1],threedskeleton.shape[2],threedskeleton.shape[3])
        rotation=torch.unsqueeze(torch.eye(3),dim=0).repeat(reshapethreed.shape[0],1,1).to(self.device)
        focal=torch.tensor([[proj]]).to(self.device).repeat(translation.shape[0],1)
        imgdimgs=torch.unsqueeze(torch.tensor([1080.0/2, 1920.0/2]),dim=0).repeat(reshapethreed.shape[0],1).to(self.device)
        twodkpts, skeleton = self.perspective_projection(reshapethreed, rotation, translation.float(),focal[:,0], imgdimgs)
        #pdb.set_trace()
        twodkpts = twodkpts.reshape(twodskeleton.shape[0],(self.train_args.step),twodkpts.shape[1],twodkpts.shape[2])
        divide = torch.unsqueeze(torch.unsqueeze(torch.unsqueeze(torch.tensor([1080.0,1920.0]),dim=0),dim=0),dim=0).repeat(twodkpts.shape[0],twodkpts.shape[1],twodkpts.shape[2],1).to(self.device)
        twodkpts = twodkpts/divide
        twodkpts = twodkpts.reshape(twodskeleton.shape[0],twodkpts.shape[1],-1)
    
        bined_left_quad = data_retval['bined_left_quad']-1
        emggroundtruth = data_retval['emg_values'].to(self.device)
        cond = data_retval['cond'].to(self.device)
        emggroundtruth = emggroundtruth/100.0

        leftquad = data_retval['left_quad'].to(self.device)
        leftquad = leftquad/100.0
        leftquad[leftquad > 1.0] = 1.0
        twodskeleton = twodskeleton.to(self.device)
        twodkpts = torch.unsqueeze(twodkpts.permute(0,2,1),dim=1)

        emg_output = self.my_model(twodkpts) 

        

        
        mask = torch.ones(emg_output.shape).type(torch.cuda.FloatTensor)
        for i in range(emg_output.shape[0]):                
            if '2423' in data_retval['frame_paths'][0][i]:
                mask[i,4,:] = 1.0
        total_loss = self.mse(emg_output*mask, (emggroundtruth*mask).type(torch.cuda.FloatTensor))

        model_retval = dict()
        model_retval['emg_output'] = emg_output[:,:,:]

        model_retval['emg_gt'] = emggroundtruth
        
        loss_retval = dict()
        loss_retval['cross_ent'] = total_loss 


        return (model_retval, loss_retval)

    def process_entire_batch(self, data_retval, model_retval, loss_retval, ignoremovie, cur_step, total_step):
        '''
        Finalizes the training step. Calculates all losses.
        :param data_retval (dict): Data loader elements.
        :param model_retval (dict): All network output information.
        :param loss_retval (dict): Preliminary loss information (per-example, but not batch-wide).
        :param cur_step (int): Current data loader index.
        :param total_step (int): Cumulative data loader index, including all previous epochs.
        :return loss_retval (dict): All loss information.
        '''
        loss_retval = self.losses.entire_batch(data_retval, model_retval, loss_retval,ignoremovie, total_step)

        return loss_retval
