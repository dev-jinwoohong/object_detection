def forward(self, predictions, targets):
    """Multibox Loss
       Args:
         predictions (tuple): A tuple containing loc 
                              preds, conf preds,
                              and prior boxes from SSD net.
           conf shape:
               torch.size(batch_size,num_priors,num_classes)
           loc shape: torch.size(batch_size,num_priors,4)
               priors shape: torch.size(num_priors,4)
         ground_truth (tensor): Ground truth boxes and 
                                labels for a batch,
             shape: [batch_size,num_objs,5] 
                    (last idx is the label).
    """
    loc_data, conf_data, priors = predictions
    num = loc_data.size(0)
    priors = priors[:loc_data.size(1), :]
    num_priors = (priors.size(0))
    num_classes = self.num_classes
    # match priors (default boxes) and ground truth boxes
    loc_t = torch.Tensor(num, num_priors, 4)
    conf_t = torch.LongTensor(num, num_priors)
    for idx in range(num):
        truths = targets[idx][:,:-1].data
        labels = targets[idx][:,-1].data
        defaults = priors.data
        match(self.threshold,truths,defaults,
              self.variance,labels,loc_t,conf_t,idx)
    if self.use_gpu:
        loc_t = loc_t.cuda()
        conf_t = conf_t.cuda()
    # wrap targets
    loc_t = Variable(loc_t, requires_grad=False)
    conf_t = Variable(conf_t,requires_grad=False)
    pos = conf_t > 0
    num_pos = pos.sum()
    # Localization Loss (Smooth L1)
    # Shape: [batch,num_priors,4]
    pos_idx = pos.unsqueeze(pos.dim()).expand_as(loc_data)
    loc_p = loc_data[pos_idx].view(-1,4)
    loc_t = loc_t[pos_idx].view(-1,4)
    loss_l = F.smooth_l1_loss(loc_p, loc_t, size_average=False)
    # Compute max conf across batch for hard negative mining
    batch_conf = conf_data.view(-1,self.num_classes)
    loss_c = log_sum_exp(batch_conf) - batch_conf.gather(
                 1,   conf_t.view(-1,1))
    # Hard Negative Mining
    loss_c[pos] = 0 # filter out pos boxes for now
    loss_c = loss_c.view(num, -1)
    _,loss_idx = loss_c.sort(1, descending=True)
    _,idx_rank = loss_idx.sort(1)
    num_pos = pos.long().sum(1)
    num_neg = torch.clamp(
        self.negpos_ratio*num_pos, max=pos.size(1)-1)
    neg = idx_rank < num_neg.expand_as(idx_rank)
    # Confidence Loss Including Positive and Negative Examples
    pos_idx = pos.unsqueeze(2).expand_as(conf_data)
    neg_idx = neg.unsqueeze(2).expand_as(conf_data)
    conf_p =  conf_data[
       (pos_idx+neg_idx).gt(0)].view(-1,self.num_classes)
    targets_weighted = conf_t[(pos+neg).gt(0)]
    loss_c = F.cross_entropy(
        conf_p, targets_weighted, size_average=False)
    # Sum of losses: L(x,c,l,g) = (Lconf(x, c) + αLloc(x,l,g)) / N
    N = num_pos.data.sum()
    loss_l/=N
    loss_c/=N
    return loss_l,loss_c